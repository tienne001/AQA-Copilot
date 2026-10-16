# Docker и Compose: окружение, сеть, readiness и логи

Тема: Docker, image, container, volume, network, Dockerfile, Compose, healthcheck, readiness, контейнер, образ. Проверка источников: 2026-10-15.

## Образ и контейнер

Image — шаблон файловой системы и метаданных запуска; container — запущенный или остановленный экземпляр с собственным изменяемым слоем. Контейнеры используют ядро среды выполнения; это не отдельная полноценная виртуальная машина. На Windows Linux-контейнеры обычно работают через Linux-среду Docker Desktop.

Volume хранит данные отдельно от изменяемого слоя контейнера. Bind mount связывает конкретный путь хоста с контейнером. Удаление контейнера и удаление volume — разные операции; тестовая очистка должна учитывать, где живут данные.

`docker compose down -v` удаляет объявленные в Compose named volumes и присоединённые anonymous volumes вместе с их данными. Это не способ сохранить данные. Volumes с `external: true` Compose не удаляет. Обычный `down` без `-v` и повторное создание контейнера с тем же named volume не равнозначны удалению этого volume.

## Compose и подключение

Compose описывает services, networks, volumes в `compose.yaml`. В общей Compose-сети сервис API может обращаться к базе по имени сервиса `db`; `localhost` внутри API-контейнера означает сам API-контейнер. При mapping `127.0.0.1:8080:3000` клиент на хосте использует порт 8080, а приложение слушает порт 3000 внутри контейнера.

Обычный порядок запуска зависимостей не гарантирует готовность базы. `healthcheck` плюс `depends_on` с `condition: service_healthy` позволяет ждать её здорового состояния при запуске; приложение всё равно должно обрабатывать последующие разрывы соединения.

Короткий `depends_on: [db]` означает зависимость запуска, а не успешный SQL-запрос к PostgreSQL. Состояние running отличается от готовности сервиса. `service_healthy` использует результат настроенного healthcheck; после старта соединение всё равно может оборваться, поэтому обработка временных отказов остаётся частью приложения.

## Учебная проверка окружения

Для существующего Compose-проекта:

```sh
docker compose config --quiet
docker compose ps
docker compose logs --tail 100 api
docker compose exec api printenv NODE_ENV
```

`config --quiet` проверяет конфигурацию. `ps` показывает состояние. Логи помогают понять причину рестарта; команда `exec` требует работающего сервиса и доступной программы. Не выводить все переменные окружения: среди них могут быть секреты.

## Ошибки и тренировка

Ошибка: «Контейнер Up, значит API работает». Нужна проверка readiness/health endpoint и реального ответа. Ошибка: использовать `latest` и ожидать полностью воспроизводимой сборки — фиксировать версии и при необходимости digest.

Вопрос: «API не соединяется с БД в Compose». Проверить имя сервиса, внутренний порт, общую сеть, readiness, credentials, строки подключения и логи обеих сторон. Публикация порта на хост не обязательна для общения сервисов внутри сети.

Источники: [Docker: container](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/), [Compose model](https://docs.docker.com/compose/intro/compose-application-model/), [startup order and healthchecks](https://docs.docker.com/compose/how-tos/startup-order/).

Источник по удалению данных: [Docker Compose down, опция --volumes](https://docs.docker.com/reference/cli/docker/compose/down/).
