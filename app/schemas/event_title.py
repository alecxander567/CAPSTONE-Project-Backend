from pydantic import BaseModel, field_validator


class EventTitleBase(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str):
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v


class EventTitleCreate(EventTitleBase):
    pass


class EventTitleResponse(EventTitleBase):
    id: int
    is_active: bool

    class Config:
        from_attributes = True