from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    """회원가입 요청."""

    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    """로그인 요청. device는 기기별 refresh token 세션을 구분한다."""

    email: EmailStr
    password: str
    device: str = "web"


class LogoutRequest(BaseModel):
    """로그아웃할 refresh token 세션을 지정하는 요청."""

    refresh_token: str


class TokenResponse(BaseModel):
    """Access/Refresh token 발급 응답."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Access Token 재발급 요청."""

    refresh_token: str
