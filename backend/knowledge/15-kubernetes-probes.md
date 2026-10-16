# Kubernetes: Pod Running, Ready и проверки состояния

Тема: Kubernetes, K8s, Pod, Running, Ready, readinessProbe, livenessProbe, startupProbe, restart count, Service, endpoints. Проверка источников: 2026-10-15.

## Readiness, liveness и startup

Readiness определяет готовность контейнера принимать трафик. Неуспешная readinessProbe сама по себе не перезапускает контейнер. Pod становится неготовым и исключается из обычного ready-трафика Service; продолжающий работать процесс может оставаться в таком состоянии до восстановления готовности.

Liveness определяет, способен ли контейнер продолжать работу. После достижения настроенного порога неудач kubelet останавливает контейнер; дальнейший запуск зависит от restart policy. Liveness не является проверкой пользовательской авторизации или гарантией корректного бизнес-ответа.

Startup probe предназначена для длительного старта. Пока она не прошла, проверки liveness и readiness этого контейнера не выполняются. Успех включает последующие проверки, а исчерпание допустимого числа неудач startup может привести к перезапуску. Startup probe не даёт контейнеру бесконечное время запуска.

## Состояние Pod и диагностика

Phase Running не означает Ready и не доказывает здоровье всех контейнеров. Pod уже назначен узлу, контейнеры созданы, хотя бы один выполняется, запускается или перезапускается. Прикладная готовность зависит от conditions и probes, а не только от общей фазы.

`kubectl describe pod` показывает conditions, состояния контейнеров, restart counts и события. `kubectl logs` относится к выбранному контейнеру; `--previous` позволяет получить логи его предыдущего экземпляра после рестарта, если они доступны. Текущий Running не исключает прежних падений.

## Источники

[Kubernetes: liveness, readiness и startup probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/).

[Kubernetes: Pod Lifecycle, conditions и container states](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/).
