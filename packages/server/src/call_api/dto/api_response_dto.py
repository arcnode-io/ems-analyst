from pydantic import BaseModel, HttpUrl


class ApiResponseDto(BaseModel):
    """API response with URL"""

    url: HttpUrl
