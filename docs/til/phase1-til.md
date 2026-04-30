# Phase 1 — TIL

## 몰랐다가 알게 된 것

- OpenTelemetry는 분산 시스템에서 세 가지 신호(Signal)를 수집하는 표준
- OpenTelemetry 3대 신호
  - Traces : 요청이 어떤 경로로 흘렀는가? ex) api-gateway -> order -> product
  - Metrics : 시스템이 지금 얼마나 건강한가? ex) 요청 수, 에러율, 응답시간 등 숫자
  - Logs : 각 시점에 무슨 일이 있었는가? ex) 구조화된 JSON 로그, trace_id 포함
- Resource 정의 -> Span 데이터 수집 -> Metric 수집 -> 자동 계측 등록의 계측 구조
- structlog 라는 모듈을 이용하여 구조화되어 가독성이 좋은 로그 생성 가능
- Python 3.10 이상부터는 Optional[T] 대신 T | None을 사용하는 것이 직관적이고 별도 import가 불필요해 보편적으로 사용
- middleware는 요청과 응답 사이에 끼어드는 레이어로 요청이 실제 비즈니스 로직(라우터/핸들러)에 도달하기 전과 후에 공통 작업을 수행

## 왜 이렇게 설계했는가 (나만의 언어로)

- shared/telemetry가 공통 모듈인 이유:
  6개 서비스 모두 OTel 초기화가 필요한데, 각자 구현하면 코드 중복 + 계측 방식 불일치 발생
- trace_id를 로그에 심는 이유:
  Grafana에서 로그 클릭하면 해당 요청의 전체 트레이스로 점프하기 위해

## 아직 불확실한 것 (다음에 확인할 것)

- MeterProvider의 export_interval이 60초면 로컬 테스트 시 너무 느리지 않을까?
- 로컬에서만 테스트했는데 실제로 컨테이너 띄우면 제대로 동작할까?
