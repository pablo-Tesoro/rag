"""Equivalent paid cost of an evaluation run.

The free tier costs nothing, so the real cost is 0. What is useful is how much the same
tokens would cost on the paid tier: that is the number a production budget would need.
Prices live in `prices.json` with their source and date; a model missing from the table
has no cost rather than a guessed one.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PRICES = Path(__file__).with_name("prices.json")


class Price(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input: float = Field(ge=0, description="USD per 1M input tokens")
    output: float = Field(ge=0, description="USD per 1M output tokens")


class PriceTable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    notice: str
    source: str
    retrieved: str
    currency: str
    unit: str
    models: dict[str, Price]

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        price = self.models.get(model)
        if price is None:
            return None
        return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


def load_prices(path: Path = PRICES) -> PriceTable:
    return PriceTable.model_validate_json(path.read_text(encoding="utf-8"))
