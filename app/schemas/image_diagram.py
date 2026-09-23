from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.chat import PlannerAction


Cardinality = Literal["1", "0..1", "0..*", "1..*"]
RelationType = Literal[
    "association",
    "generalization",
    "composition",
    "aggregation",
    "associationClass",
    "realization",
    "templateBinding",
]
ClassKind = Literal["class", "abstractClass", "interface"]


class ImageParameter(BaseModel):
    name: str
    type: str = "Object"


class ImageMethod(BaseModel):
    name: str
    returnType: str = "void"
    parameters: list[ImageParameter] = Field(default_factory=list)


class ImageAttribute(BaseModel):
    name: str
    type: str = "VARCHAR"
    primaryKey: bool = False
    foreignKey: bool = False
    nullable: bool = True


class ImageClass(BaseModel):
    name: str
    kind: ClassKind = "class"
    attributes: list[ImageAttribute] = Field(default_factory=list)
    methods: list[ImageMethod] = Field(default_factory=list)
    templateParameters: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0, le=1)


class ImageRelation(BaseModel):
    sourceName: str
    targetName: str
    relationType: RelationType
    sourceCardinality: Cardinality | None = None
    targetCardinality: Cardinality | None = None
    associationClassName: str | None = None
    sourceRole: str | None = None
    targetRole: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)


class ImageDiagramResponse(BaseModel):
    summary: str
    classes: list[ImageClass] = Field(default_factory=list)
    relations: list[ImageRelation] = Field(default_factory=list)
    actions: list[PlannerAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    can_execute: bool = False
    image_metadata: dict[str, Any] = Field(default_factory=dict)
