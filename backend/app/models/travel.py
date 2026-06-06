"""Pydantic models for the intelligent travel assistant."""

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


BudgetLevel = Literal["economy", "comfort", "premium"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class Location(BaseModel):
    """Geographic coordinate."""

    longitude: float = Field(..., description="Longitude", ge=-180, le=180)
    latitude: float = Field(..., description="Latitude", ge=-90, le=90)


class Attraction(BaseModel):
    """Attraction information normalized from POI search results."""

    name: str = Field(..., description="Attraction name")
    address: str = Field(..., description="Address")
    location: Location = Field(..., description="Coordinate")
    visit_duration: int = Field(..., description="Suggested visit minutes", gt=0)
    description: str = Field(..., description="Description")
    category: str | None = Field(default="attraction", description="Category")
    rating: float | None = Field(default=None, ge=0, le=5, description="Rating")
    image_url: str | None = Field(default=None, description="Image URL")
    ticket_price: int = Field(default=0, ge=0, description="Ticket price")


class Meal(BaseModel):
    """Meal arrangement."""

    type: MealType = Field(..., description="Meal type")
    name: str = Field(..., description="Meal name")
    address: str | None = Field(default=None, description="Address")
    location: Location | None = Field(default=None, description="Coordinate")
    description: str | None = Field(default=None, description="Description")
    estimated_cost: int = Field(default=0, ge=0, description="Estimated cost")


class Hotel(BaseModel):
    """Hotel information normalized from POI search results."""

    name: str = Field(..., description="Hotel name")
    address: str = Field(default="", description="Hotel address")
    location: Location | None = Field(default=None, description="Hotel coordinate")
    price_range: str = Field(default="", description="Price range")
    rating: str = Field(default="", description="Rating")
    distance: str = Field(default="", description="Distance from attractions")
    type: str = Field(default="", description="Hotel type")
    estimated_cost: int = Field(default=0, ge=0, description="Estimated cost per night")


class Budget(BaseModel):
    """Budget summary."""

    total_attractions: int = Field(default=0, ge=0, description="Attraction tickets")
    total_hotels: int = Field(default=0, ge=0, description="Hotel cost")
    total_meals: int = Field(default=0, ge=0, description="Meal cost")
    total_transportation: int = Field(default=0, ge=0, description="Transport cost")
    total: int = Field(default=0, ge=0, description="Total cost")


class DayPlan(BaseModel):
    """Single day travel plan."""

    date: Date = Field(..., description="Date")
    day_index: int = Field(..., description="Day index, starting from 0", ge=0)
    description: str = Field(..., description="Daily summary")
    transportation: str = Field(..., description="Transportation")
    accommodation: str = Field(..., description="Accommodation arrangement")
    hotel: Hotel | None = Field(default=None, description="Hotel")
    attractions: list[Attraction] = Field(default_factory=list, description="Attractions")
    meals: list[Meal] = Field(default_factory=list, description="Meals")


class WeatherInfo(BaseModel):
    """Weather information normalized from weather search results."""

    date: Date = Field(..., description="Date")
    day_weather: str = Field(..., description="Day weather")
    night_weather: str = Field(..., description="Night weather")
    day_temp: int = Field(..., description="Day temperature in Celsius")
    night_temp: int = Field(..., description="Night temperature in Celsius")
    wind_direction: str = Field(..., description="Wind direction")
    wind_power: str = Field(..., description="Wind power")

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, value: object) -> int:
        """Parse values like 16C, 16 deg C, 16°C or 16℃ into integers."""

        if isinstance(value, str):
            normalized = (
                value.replace("°C", "")
                .replace("℃", "")
                .replace("°", "")
                .replace("C", "")
                .replace("celsius", "")
                .replace("deg", "")
                .strip()
            )
            try:
                return int(normalized)
            except ValueError:
                return 0
        return int(value)


class TripPlan(BaseModel):
    """Complete travel plan."""

    city: str = Field(..., description="Destination city")
    start_date: Date = Field(..., description="Start date")
    end_date: Date = Field(..., description="End date")
    days: list[DayPlan] = Field(default_factory=list, description="Daily plans")
    weather_info: list[WeatherInfo] = Field(default_factory=list, description="Weather")
    overall_suggestions: str = Field(..., description="Overall suggestions")
    budget: Budget | None = Field(default=None, description="Budget")


class TravelPlanRequest(BaseModel):
    """Request sent by the frontend travel planning form."""

    city: str = Field(..., min_length=1, description="Destination city")
    start_date: Date = Field(..., description="Start date")
    end_date: Date = Field(..., description="End date")
    travelers: int = Field(default=1, ge=1, le=20, description="Traveler count")
    budget_level: BudgetLevel = Field(default="comfort", description="Budget level")
    budget: int | None = Field(default=None, ge=0, description="Optional total budget")
    preferences: list[str] = Field(default_factory=list, description="Travel preferences")
    transportation: str = Field(default="public transit + walking", description="Transport")
    accommodation: str = Field(default="comfort", description="Accommodation type")

    @property
    def days_count(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, end_date: Date, info: ValidationInfo) -> Date:
        start_date = info.data.get("start_date")
        if start_date and end_date < start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return end_date


class TravelPlanResponse(BaseModel):
    """API response wrapper."""

    plan: TripPlan
