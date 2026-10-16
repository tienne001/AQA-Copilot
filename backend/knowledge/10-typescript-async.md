# TypeScript и JavaScript: unknown, narrowing, Promise и await

Тема: TypeScript, JavaScript, async, await, Promise.all, unknown, any, type guard, narrowing, runtime validation. Проверка источников: 2026-10-15.

## Типы и данные API

TypeScript проверяет типы при разработке; обычные типы не проверяют внешний JSON во время выполнения. `any` отключает полезные проверки. `unknown` требует сузить тип перед использованием. Narrowing использует условия `typeof`, проверки свойств, discriminated unions или type guards. Type assertion `as Order` сообщает компилятору предположение и не доказывает корректность ответа.

## Учебная проверка внешнего значения

```ts
type Order = { id: string; status: string };

function isOrder(value: unknown): value is Order {
  return typeof value === 'object' && value !== null
    && 'id' in value && typeof value.id === 'string'
    && 'status' in value && typeof value.status === 'string';
}

const payload: unknown = JSON.parse('{"id":"42","status":"created"}');
if (!isOrder(payload)) throw new Error('Некорректный заказ');
console.log(payload.id);
```

Этот guard проверяет только два поля; допустимые статусы, дополнительные поля и бизнес-правила требуют отдельной валидации.

## Async и параллельность

`async` функция возвращает Promise. `await` приостанавливает продолжение этой функции до результата, но не блокирует весь JavaScript поток как синхронное ожидание.

`await Promise.all([loadA(), loadB()])` подходит для независимых операций. Результаты расположены в порядке входных promises, независимо от порядка завершения. При первом rejection общий promise отклоняется; уже начатые операции автоматически не отменяются. Для получения всех исходов использовать `Promise.allSettled`. Зависимые шаги выполнять последовательно: сначала создать заказ, затем читать его по полученному id.

## Ошибки и тренировка

`forEach(async () => ...)` не ожидает завершения callbacks. Для последовательной обработки использовать `for...of` с await; для управляемой параллельности — promises и ограничение нагрузки. В тесте всегда ожидать асинхронные действия и assertions.

Вопрос: «Promise.all отменяет остальные запросы после ошибки?» Нет. Нужна явная поддержка отмены в вызываемом API, например AbortSignal для совместимых операций.

Источники: [TypeScript narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html), [TypeScript type checking](https://www.typescriptlang.org/docs/handbook/2/basic-types.html), [MDN Promise.all](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all), [MDN async function](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/async_function).
