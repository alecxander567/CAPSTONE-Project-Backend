from pydantic import BaseModel, field_validator


class LocationBase(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str):
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v


class LocationCreate(LocationBase):
    pass


class LocationResponse(LocationBase):
    id: int
    is_active: bool

    class Config:
        from_attributes = True