from enum import StrEnum

from pydantic import BaseModel

from backend.services.dashboard.semantic_layer import DimensionName, MeasureName


class ChartType(StrEnum):
    """패널 하나를 그리는 방식."""

    KPI = "kpi"
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    TABLE = "table"


class PanelPlan(BaseModel):
    """대시보드의 패널 하나. 측정값 하나를 기준 하나로 나눠 본다.

    dimension이 없으면 나누지 않은 숫자 하나(KPI)다.
    """

    # 이 docstring과 필드 순서는 그대로 Gemini에 스키마로 전달된다(query_parser.ParsedQuery 참고).
    # measure·dimension이 enum이라 모델은 레이어에 있는 이름만 고를 수 있다.
    title: str
    measure: MeasureName
    dimension: DimensionName | None = None
    chart: ChartType
    limit: int | None = None


class DashboardPlan(BaseModel):
    """사용자 질의를 시멘틱 레이어로 옮긴 대시보드 구성."""

    # unsupported를 맨 앞에 두는 것은 만들 수 있는지부터 따지게 하려는 것이다. 패널을 먼저 채우게
    # 하면 '체류 시간'을 본문 길이로 바꿔치는 식으로 어떻게든 채운 뒤 unsupported를 비워 둔다.
    unsupported: list[str] = []
    title: str = ""
    sites: list[str] = []
    keywords: list[str] = []
    panels: list[PanelPlan] = []


class DashboardPoint(BaseModel):
    """차트의 점 하나. key는 정렬·식별용 원래 값, label은 화면에 적을 말이다.

    key와 label을 나누는 것은 요일(0 -> '월')이나 날짜('2026-08-31' -> '8/31')처럼 둘이 다른
    경우가 있어서다. 프론트엔드가 같은 변환을 다시 구현하지 않아도 된다.
    """

    key: str
    label: str
    value: float


class DashboardPanel(BaseModel):
    title: str
    chart: ChartType
    measure: MeasureName
    measure_label: str
    unit: str
    dimension: DimensionName | None = None
    dimension_label: str | None = None
    points: list[DashboardPoint] = []


class Dashboard(BaseModel):
    """실행을 마친 대시보드. 화면이 그대로 그리며, 대화에도 이 모양 그대로 저장된다.

    period와 filters는 사람 말로 적은 조건이다. 차트만 보고는 어느 기간·어느 사이트로 걸렀는지
    알 수 없어 함께 보여줘야 한다. notes는 숫자를 읽을 때 알아야 할 단서다(재방문을 세지 않는다 등).
    """

    title: str
    period: str
    filters: list[str] = []
    panels: list[DashboardPanel]
    notes: list[str] = []
