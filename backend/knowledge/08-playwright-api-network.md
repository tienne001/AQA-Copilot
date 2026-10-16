# Playwright: APIRequestContext, network mock и изоляция

Тема: Playwright, API testing, request fixture, APIRequestContext, route, mock, waitForResponse, BrowserContext, isolation, cookies. Проверка источников: 2026-10-15.

## API и состояние

Playwright позволяет делать HTTP-запросы напрямую: подготовить данные через API, проверить ответ или постусловия после UI. В Playwright Test fixture `request` даёт изолированный APIRequestContext. `page.request` и `context.request` связаны с cookies своего BrowserContext; отдельный `request.newContext()` имеет собственное cookie storage.

По умолчанию Playwright Test создаёт новый BrowserContext для каждого теста: cookies/localStorage не перетекают между тестами. Серверная база при этом общая, поэтому нужны уникальные тестовые данные и контролируемая очистка. Отдельный browser context не изолирует внешнюю БД.

## Учебный API-тест

Предполагается baseURL и учебный контракт `POST /orders → 201, {id,status}`:

```ts
import { test, expect } from '@playwright/test';

test('создание заказа', async ({ request }) => {
  const response = await request.post('/orders', {
    data: { productId: 'fixture-product', quantity: 1 },
  });
  expect(response.status()).toBe(201);
  const order = await response.json();
  expect(order.id).toEqual(expect.any(String));
  expect(order.status).toBe('created');
});
```

В реальном проекте добавить авторизацию, схему ответа и очистку по контракту. Проверка JSON через TypeScript type assertion не валидирует данные во время выполнения.

## Mock и ожидание ответа

`page.route('**/api/catalog', route => route.fulfill({json: ...}))` позволяет задать контролируемый ответ. Регистрировать route до действия, которое отправит запрос. Такой тест проверяет UI на известном контракте; отдельный интеграционный тест нужен для настоящего backend.

При `waitForResponse` создать promise до click, затем дождаться его. В predicate проверять точный URL/метод и нужный статус, чтобы не поймать посторонний запрос. Если route не ловит запрос, проверить Service Worker; настройки блокировки менять осознанно для тестового проекта.

Вопрос: «Можно авторизоваться один раз для всех тестов?» Сохранённый storageState удобен, но общая учётная запись и изменяемые серверные данные могут конфликтовать при параллельности; сессии и секреты не коммитить.

Источники: [API testing](https://playwright.dev/docs/api-testing), [network mocking](https://playwright.dev/docs/network), [browser isolation](https://playwright.dev/docs/browser-contexts).
