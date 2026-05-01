"""
RS256 키페어 생성 스크립트
최초 1회만 실행합니다. 생성된 .pem 파일은 절대 Git에 커밋하지 마세요.

실행: python scripts/generate_keys.py
결과: keys/private.pem, keys/public.pem 생성
"""

import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# keys 디렉토리 생성
os.makedirs("keys", exist_ok=True)

# RSA 키페어 생성
# key_size=2048: 현재 보안 표준. 4096은 더 안전하지만 서명 속도 느림
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend(),
)

# 개인키 저장 (user-service 전용, 절대 외부 노출 금지)
with open("keys/private.pem", "wb") as f:
    f.write(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),  # 로컬 개발용
        )
    )

# 공개키 저장 (api-gateway에서 JWT 검증용으로 사용)
public_key = private_key.public_key()
with open("keys/public.pem", "wb") as f:
    f.write(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

print("키페어 생성 완료")
print("keys/private.pem — user-service 전용 (절대 커밋 금지)")
print("keys/public.pem  — api-gateway용 (커밋 가능)")
