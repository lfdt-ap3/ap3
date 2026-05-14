from __future__ import annotations

import os
import uvicorn


def main() -> None:
    uvicorn.run(
        "ap3_playground.server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8088")),
        reload=os.getenv("RELOAD", "").lower() in {"1", "true", "yes"},
        log_level="info",
    )


if __name__ == "__main__":
    main()

