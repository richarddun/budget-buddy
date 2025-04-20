from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models import StreamedResponse
from pydantic_ai.messages import ToolCallPart, ToolReturnPart, TextPart, ToolCallPartDelta, ModelResponse, ModelResponseStreamEvent
from pydantic_ai._utils import PeekableAsyncStream, Unset
from typing import AsyncIterator, List
from collections.abc import AsyncIterable, AsyncIterator, Sequence
import datetime
import json
import logging

logger = logging.getLogger("shimfinity")
logger.setLevel(logging.INFO)

async def _fake_stream_tool_event(parsed):
    yield ToolCallPartDelta(
        index=0,
        tool_name=parsed["name"],
        args_delta=parsed["parameters"],
        tool_call_id="shim-stream-001"
        )
    
class LlamaShimModel(OpenAIModel):
    def _process_response(self, response):
        response = super()._process_response(response)

        if any(isinstance(p, ToolCallPart) for p in response.parts):
            logger.info("✅ ToolCallPart already detected — no shim needed.")
            return response

        if len(response.parts) == 1 and isinstance(response.parts[0], TextPart):
            try:
                maybe = json.loads(response.parts[0].content)
                if "name" in maybe and "parameters" in maybe:
                    logger.info("✅ Shimmed ToolCallPart from JSON detected.")


                    return ModelResponseStreamEvent(
                        events=[
                            ToolCallPartDelta(
                                tool_name_delta=parsed["name"],
                                args_delta=parsed["parameters"],
                                tool_call_id="shim-stream-001"
                            )
                        ],
                        model_name=self.model_name
                    )

            except Exception as e:
                logger.warning(f"⚠️ Failed to parse as tool JSON: {e}")

        return response


    async def _process_streamed_response(self, response):
        stream = PeekableAsyncStream(response)
        buffered = ""
        max_tokens = 60
        for i in range(max_tokens):
            next_chunk = await stream.peek()
            if isinstance(next_chunk, Unset):
                break

            # Consume it now that we've peeked
            chunk = await stream.__anext__()
            delta = chunk.choices[0].delta.content or ""
            buffered += delta

            try:
                parsed = json.loads(buffered)
                if "name" in parsed and "parameters" in parsed:
                    print(f"✅ Shimfinity intercepted streamed tool call: {parsed}")
                return ShimToolCallStreamedResponse(
                    tool_name=parsed["name"],
                    args=parsed["parameters"],
                    tool_call_id="shim-stream-001",
                    model_name=self.model_name
                )

            except json.JSONDecodeError:
                continue  # Buffer more chunks
            except Exception as e:
                print(f"⚠️ Unexpected error while parsing: {e}")
                break

        print("ℹ️ No structured tool call found — falling back to default streaming handler.")
        return await super()._process_streamed_response(response)

class ShimToolCallStreamedResponse(StreamedResponse):
    def __init__(self, tool_name: str, args: dict, tool_call_id: str, model_name: str):
        self._tool_name = tool_name
        self._args = args
        self._tool_call_id = tool_call_id
        self._model_name = model_name
        self._timestamp = datetime.datetime.now(datetime.timezone.utc)

    async def __aiter__(self):
        yield ToolCallPartDelta(
            tool_name_delta=self._tool_name,
            args_delta=self._args,
            tool_call_id=self._tool_call_id,
        )

    async def _get_event_iterator(self):
        raise NotImplementedError("_get_event_iterator is not used by ShimToolCallStreamedResponse")

    def get(self) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(
                tool_name=self._tool_name,
                args=self._args,
                tool_call_id=self._tool_call_id
            )],
            model_name=self._model_name,
            timestamp=self._timestamp
        )

    def usage(self):
        from pydantic_ai.usage import Usage
        return Usage(requests=1, request_tokens=0, response_tokens=0, total_tokens=0)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def timestamp(self) -> datetime:
        return self._timestamp