-- MicroMart 로컬 개발용 DB/유저 초기화
-- PostgreSQL 컨테이너 최초 시작 시 1회 자동 실행됩니다.

-- user-service DB
-- CREATE DATABASE userdb;

-- product-service DB
CREATE DATABASE productdb;

-- order-service DB
CREATE DATABASE orderdb;

-- payment-service DB
CREATE DATABASE paymentdb;

-- 각 서비스는 동일한 유저를 공유합니다 (로컬 개발 편의상)
-- 운영 환경에서는 서비스별로 별도 유저와 최소 권한을 부여합니다
GRANT ALL PRIVILEGES ON DATABASE userdb TO micromart;
GRANT ALL PRIVILEGES ON DATABASE productdb TO micromart;
GRANT ALL PRIVILEGES ON DATABASE orderdb TO micromart;
GRANT ALL PRIVILEGES ON DATABASE paymentdb TO micromart;
