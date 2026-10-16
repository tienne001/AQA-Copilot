# Playwright UI: locators, auto-wait и устойчивые assertions

Тема: Playwright, TypeScript, UI, locator, getByRole, getByTestId, auto-waiting, actionability, assertion, flaky test, ожидание. Проверка источников: 2026-10-15.

## Выбор элемента

Locator описывает способ находить элемент заново перед действиями. Предпочитать пользовательские признаки: роль и accessible name, label, текст; для технического контракта — test id. CSS/XPath допустимы, но длинная цепочка DOM зависит от структуры страницы.

Операция, требующая один элемент, обычно выдаёт strictness error при нескольких совпадениях. Уточнять область поиска, например нужную строку или карточку, вместо случайного `.first()`. `getByRole` опирается на accessibility semantics; имя может отличаться от видимого текста.

## Ожидания

Page Object Model (POM) организует действия и локаторы вокруг страницы или переиспользуемого компонента. Это не обязательный отдельный класс на каждый DOM-элемент и не механизм изоляции тестов. Состояние cookies и storage изолируется BrowserContext; стандартная test-фикстура page относится к отдельному тесту. Общая глобальная page может передавать состояние между тестами, даже если используются page objects.

Перед `click` Playwright проверяет, что элемент видим, стабилен, принимает события и enabled, а locator разрешается однозначно. Auto-wait не означает, что бизнес-операция завершилась. Web-first assertion `await expect(locator).toHaveText(...)` повторяет проверку до таймаута; обычный `expect(await locator.textContent()).toBe(...)` проверяет один снимок.

## Учебный пример

В Playwright Test настроен baseURL, а приложение содержит доступные label и кнопку:

```ts
import { test, expect } from '@playwright/test';

test('поиск товара', async ({ page }) => {
  await page.goto('/catalog');
  await page.getByLabel('Поиск').fill('Клавиатура');
  await page.getByRole('button', { name: 'Найти', exact: true }).click();
  await expect(page.getByTestId('search-results'))
    .toContainText('Клавиатура');
});
```

Проверяемый результат должен отличать успех от старого состояния: при необходимости сначала убедиться в исходных данных или ожидать конкретный результат текущего запроса.

## Ошибки и тренировка

Фиксированный sleep замедляет тест и не устраняет гонку. `force: true` обходится без части actionability-проверок и способен скрыть реальную проблему UI. Забытый `await` позволяет тесту завершиться до проверки.

Вопрос: «Кнопка visible, почему click не проходит?» Может быть overlay, анимация, disabled, несколько совпадений или смена DOM. Посмотреть trace и конкретную ошибку, затем уточнить locator или ожидаемое состояние.

Источники: [Playwright locators](https://playwright.dev/docs/locators), [auto-waiting](https://playwright.dev/docs/actionability).
