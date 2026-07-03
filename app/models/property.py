"""
Property-related Pydantic models
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from datetime import datetime, date


# Enums
PropertyType = Literal["apartment", "house", "duplex", "studio", "penthouse"]
PropertyStatus = Literal["draft", "active", "rented", "inactive", "vacant"]


# Request Models
class PropertyCreate(BaseModel):
    """Create property request"""
    title: str = Field(..., min_length=10, max_length=200)
    description: Optional[str] = None
    rent_amount: float = Field(..., gt=0)
    security_deposit: Optional[float] = Field(None, ge=0)
    location: str = Field(..., min_length=3)
    address: Optional[str] = None
    city: str = "Lagos"
    state: str = "Lagos"
    country: str = "Nigeria"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    bedrooms: int = Field(..., ge=0, le=20)
    bathrooms: int = Field(1, ge=1, le=10)
    square_feet: Optional[int] = Field(None, gt=0)
    property_type: PropertyType = "apartment"
    amenities: list[str] = []
    photos: list[str] = []
    availability_start: Optional[date] = None
    status: PropertyStatus = "draft"


class PropertyUpdate(BaseModel):
    """Update property request"""
    title: Optional[str] = Field(None, min_length=10, max_length=200)
    description: Optional[str] = None
    rent_amount: Optional[float] = Field(None, gt=0)
    security_deposit: Optional[float] = Field(None, ge=0)
    location: Optional[str] = None
    address: Optional[str] = None
    bedrooms: Optional[int] = Field(None, ge=0, le=20)
    bathrooms: Optional[int] = Field(None, ge=1, le=10)
    square_feet: Optional[int] = Field(None, gt=0)
    property_type: Optional[PropertyType] = None
    amenities: Optional[list[str]] = None
    photos: Optional[list[str]] = None
    availability_start: Optional[date] = None
    status: Optional[PropertyStatus] = None


class PropertySearch(BaseModel):
    """Property search filters"""
    location: Optional[str] = None
    min_budget: Optional[float] = Field(None, ge=0)
    max_budget: Optional[float] = Field(None, ge=0)
    bedrooms: Optional[int] = Field(None, ge=0)
    bathrooms: Optional[int] = Field(None, ge=1)
    property_type: Optional[PropertyType] = None
    amenities: Optional[list[str]] = None
    sort: Literal["newest", "price_low", "price_high"] = "newest"
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


# Response Models
class LandlordInfo(BaseModel):
    """Landlord information in property response"""
    id: str
    name: Optional[str]
    avatar_url: Optional[str]
    trust_score: int
    verified: bool
    properties_count: int = 0
    joined_year: int
    guarantee_joined: bool = False


class PropertyResponse(BaseModel):
    """Property response"""
    id: str
    landlord_id: str
    title: str
    description: Optional[str]
    rent_amount: float = Field(alias="price")
    security_deposit: Optional[float] = None
    agency_fee: float = 0  # Always 0 for Nulo!
    location: str
    address: Optional[str]
    city: str
    state: str
    country: str
    latitude: Optional[float]
    longitude: Optional[float]
    bedrooms: int = Field(alias="beds")
    bathrooms: int = Field(alias="baths")
    square_feet: Optional[int] = Field(None, alias="sqft")
    property_type: PropertyType
    amenities: list[str] = []
    photos: list[str] = Field(default=[], alias="images")
    availability_start: Optional[date] = Field(None, alias="available_from")
    status: PropertyStatus
    view_count: int = 0
    favorite_count: int = 0
    application_count: int = 0
    slug: Optional[str] = None
    verified: bool = False
    verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    # Joined data
    landlord: Optional[LandlordInfo] = None
    is_favorited: bool = False
    
    class Config:
        from_attributes = True
        populate_by_name = True


class PropertyListResponse(BaseModel):
    """Paginated property list response"""
    success: bool = True
    properties: list[PropertyResponse]
    pagination: dict = {
        "total": 0,
        "page": 1,
        "limit": 20,
        "total_pages": 0,
    }
