from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    price: int = Field(..., gt=0, description="원 단위 가격")
    stock: int = Field(..., ge=0, description="재고 수량 (음수 불가)")


class ProductCreate(ProductBase):
    """상품 등록 요청."""

    pass


class ProductUpdate(BaseModel):
    """상품 수정 요청. 모든 필드 optional (PATCH 의미론)."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    price: int | None = Field(None, gt=0)
    stock: int | None = Field(None, ge=0)
    is_active: bool | None = None


class ProductResponse(ProductBase):
    """상품 응답. version 포함 (클라이언트가 낙관적 잠금 버전 확인 가능)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    """목록 조회 응답: 커서 대신 offset 페이지네이션 (단순성 우선)."""

    items: list[ProductResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


class StockDeductRequest(BaseModel):
    """
    재고 차감 요청 (order-service → product-service).

    quantity: 차감할 수량
    expected_version: 낙관적 잠금용 현재 버전.
                      order-service가 상품 조회 시 받은 version을 그대로 전달.
                      서버의 실제 version과 다르면 409 반환 → order-service 재시도.
    """

    quantity: int = Field(..., gt=0, description="차감 수량 (1 이상)")
    expected_version: int = Field(..., gt=0, description="낙관적 잠금용 버전")


class StockDeductResponse(BaseModel):
    """재고 차감 성공 응답."""

    product_id: int
    remaining_stock: int
    new_version: int


class ErrorResponse(BaseModel):
    """에러 응답 표준 형식."""

    detail: str
    code: str | None = None  # 클라이언트가 에러 종류를 구분할 수 있도록
