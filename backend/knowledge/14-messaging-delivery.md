# RabbitMQ и Kafka: подтверждение доставки и обработка сообщений

Тема: RabbitMQ, Kafka, autoAck, manual ack, publisher confirm, consumer ack, offset commit, consumer group, partition, повторная доставка. Проверка источников: 2026-10-15.

## RabbitMQ: automatic и manual acknowledgement

При `autoAck=true` RabbitMQ считает доставку принятой сразу после отправки сообщения. Отдельного ручного ack от consumer нет. Падение consumer до завершения бизнес-операции не гарантирует возврат сообщения в очередь; результат обработки может быть потерян. Успешная доставка в TCP-соединение не доказывает успешную запись в БД.

При manual ack сообщение подтверждается consumer после успешной обработки. Неподтверждённая доставка может быть возвращена в очередь при закрытии соединения или канала. Сбой после записи результата, но до ack, допускает повторную обработку. Ручное подтверждение не означает отсутствие дубликатов; идемпотентный обработчик или дедупликация учитывают этот сценарий.

Publisher confirm относится к взаимодействию publisher с брокером, а consumer ack — к доставке и обработке на стороне consumer. Эти механизмы независимы. Publisher confirm не подтверждает выполнение бизнес-операции или запись в БД consumer; для такого результата используется прикладной ответ, событие или статус операции.

## Kafka: partitions, consumer group и offset

В обычной Kafka consumer group каждая назначенная partition читается одним consumer этой группы. Число одновременно занятых consumer ограничено числом partitions; лишние consumer могут простаивать. Записи упорядочены внутри partition по offset. Между разными partitions единого порядка событий не гарантируется.

Commit offset сохраняет позицию восстановления consumer, а не атомарно подтверждает внешнюю бизнес-операцию. Commit до обработки допускает пропуск ещё не выполненной операции после сбоя. Commit после записи результата допускает повтор этой записи, если сбой произошёл до commit. Идемпотентность или согласование результата с позицией решают отдельную задачу от порядка commit.

## Источники

[RabbitMQ: Consumers и acknowledgement modes](https://www.rabbitmq.com/docs/consumers).

[RabbitMQ: consumer acknowledgements и publisher confirms](https://www.rabbitmq.com/docs/confirms).

[Apache Kafka: KafkaConsumer, группы и позиции](https://kafka.apache.org/41/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html).

[Apache Kafka: delivery semantics](https://kafka.apache.org/41/design/design/).
