import logging
import json
import os

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig
from pydantic import Field


logger = logging.getLogger(__name__)


class RotFunctionConfig(FunctionBaseConfig, name="rot"):
    description: str = Field(
        default="RENKAI deterministic multi-agent orchestrator"
    )


@register_function(config_type=RotFunctionConfig)
async def rot_function(
    config: RotFunctionConfig,
    builder: Builder,
):
    router_fn = await builder.get_function("router")
    deerflow_fn = await builder.get_function("deerflow_agent")
    planner_fn = await builder.get_function("planner")
    constructor_fn = await builder.get_function("constructor")
    inspector_fn = await builder.get_function("inspector")

    async def _response_fn(input_message: str) -> str:

        logger.info("[RENKAI] Starting request")

        # --------------------------------------------------
        # STEP 1 — ROUTER
        # --------------------------------------------------

        logger.info("[RENKAI] Step 1: Router")

        routing_result = await router_fn.ainvoke(input_message)

        logger.info(
            f"[RENKAI] Router result: {routing_result}"
        )

        try:
            routing = json.loads(routing_result)
        except Exception:
            return (
                "RENKAI ERROR: Router returned invalid JSON.\n\n"
                f"Router output:\n{routing_result}"
            )

        lane = routing.get("lane")

        # --------------------------------------------------
        # STEP 2 — RESEARCH / DIRECT ANSWER
        # --------------------------------------------------

        logger.info(
            f"[RENKAI] Route selected: {lane}"
        )

        deerflow_result = await deerflow_fn.ainvoke(
            input_message
        )

        # Direct informational request
        if lane == "deerflow_direct":

            logger.info(
                "[RENKAI] Direct answer completed"
            )

            return deerflow_result

        # --------------------------------------------------
        # STEP 3 — PLANNER
        # --------------------------------------------------

        if lane != "build_pipeline":
            return (
                f"RENKAI ERROR: Unknown routing lane: {lane}"
            )

        logger.info(
            "[RENKAI] Step 3: Planner"
        )

        planner_result = await planner_fn.ainvoke(
            input_message
        )

        try:
            planner_payload = json.loads(planner_result)
        except Exception:
            planner_payload = {}

        if not planner_payload or planner_payload.get("status") == "failed" or not planner_payload.get("algorithm_steps"):
            logger.error("[RENKAI] Planner failed — stopping build pipeline")
            return (
                "RENKAI build pipeline failed.\n\n"
                f"Planner:\n{planner_result}\n\n"
                "Constructor:\nNot run\n\n"
                "Inspector:\nNot run"
            )

        logger.info(
            "[RENKAI] Planner completed"
        )

        # --------------------------------------------------
        # STEP 4 — CONSTRUCTOR
        # --------------------------------------------------

        logger.info(
            "[RENKAI] Step 4: Constructor"
        )

        constructor_result = await constructor_fn.ainvoke(
            "build"
        )

        if not constructor_result or "ERROR:" in str(constructor_result):
            logger.error("[RENKAI] Constructor failed — stopping build pipeline")
            return (
                "RENKAI build pipeline failed.\n\n"
                f"Planner:\n{planner_result}\n\n"
                f"Constructor:\n{constructor_result}\n\n"
                "Inspector:\nNot run"
            )

        logger.info(
            "[RENKAI] Constructor completed"
        )

        # Constructor owns Python self-repair and invokes Inspector while it
        # repairs. Run the explicit final build-stage verdict only for valid Python plans.
        inspector_result = "Not run (non-Python output)."
        if str(planner_payload.get("output_type", "")).lower() == "python":
            if not os.path.exists(os.path.join("runtime", "outputs", "output.py")):
                logger.error("[RENKAI] No Python artifact produced for valid plan")
                return (
                    "RENKAI build pipeline failed.\n\n"
                    f"Planner:\n{planner_result}\n\n"
                    f"Constructor:\n{constructor_result}\n\n"
                    "Inspector:\nNot run (no output.py artifact)"
                )
            logger.info("[RENKAI] Inspector started")
            inspector_result = await inspector_fn.ainvoke("check")
            if "OVERALL STATUS: PASSED" in inspector_result:
                logger.info("[RENKAI] Inspector result: PASSED")
            else:
                logger.error("[RENKAI] Inspector result: FAILED")
                return (
                    "RENKAI build pipeline failed.\n\n"
                    f"Planner:\n{planner_result}\n\n"
                    f"Constructor:\n{constructor_result}\n\n"
                    f"Inspector:\n{inspector_result}"
                )

        # --------------------------------------------------
        # FINAL RESPONSE
        # --------------------------------------------------

        return (
            "RENKAI build pipeline completed.\n\n"
            f"Planner:\n{planner_result}\n\n"
            f"Constructor:\n{constructor_result}\n\n"
            f"Inspector:\n{inspector_result}"
        )

    yield FunctionInfo.create(
        single_fn=_response_fn,
        description=config.description,
    )
