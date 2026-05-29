"""OpenAI LLM client implementation."""

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from ..retry import RetryConfig, async_retry
from ..schema import FunctionCall, LLMResponse, Message, TokenUsage, ToolCall
from .base import LLMClientBase

logger = logging.getLogger(__name__)


class OpenAIClient(LLMClientBase):
    """LLM client using OpenAI's protocol.

    This client uses the official OpenAI SDK and supports:
    - Reasoning content (via reasoning_split=True)
    - Tool calling
    - Retry logic
    """

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://api.minimaxi.com/v1",
        model: str = "MiniMax-M2.5",
        retry_config: RetryConfig | None = None,
    ):
        """Initialize OpenAI client.

        Args:
            api_key: API key for authentication
            api_base: Base URL for the API (default: MiniMax OpenAI endpoint)
            model: Model name to use (default: MiniMax-M2.5)
            retry_config: Optional retry configuration
        """
        super().__init__(api_key, api_base, model, retry_config)

        # Initialize OpenAI client
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
        )

    async def _make_api_request(
        self,
        api_messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
    ) -> Any:
        """Execute API request (core method that can be retried).

        Args:
            api_messages: List of messages in OpenAI format
            tools: Optional list of tools

        Returns:
            OpenAI ChatCompletion response (full response including usage)

        Raises:
            Exception: API call failed
        """
        params = {
            "model": self.model,
            "messages": api_messages,
            # Enable reasoning_split to separate thinking content
            "extra_body": {"reasoning_split": True},
        }

        if tools:
            params["tools"] = self._convert_tools(tools)

        # Use OpenAI SDK's chat.completions.create
        response = await self.client.chat.completions.create(**params)
        # Return full response to access usage info
        return response

    async def _emit_stream_callback(self, content: str) -> None:
        """Emit incremental streaming content to the registered callback."""
        if not self.stream_callback:
            return

        event_data = {
            "event": "message",
            "content": content,
        }

        try:
            result = self.stream_callback(event_data)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning("Stream callback error: %s", e)

    async def _make_stream_api_request(
        self,
        api_messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
    ) -> LLMResponse:
        """Execute a streaming API request and build an LLMResponse from chunks."""
        params = {
            "model": self.model,
            "messages": api_messages,
            "extra_body": {"reasoning_split": True},
            "stream": True,
        }

        if tools:
            params["tools"] = self._convert_tools(tools)

        full_content = ""
        thinking_content = ""
        finish_reason = "stop"
        tool_call_parts: dict[int, dict[str, Any]] = {}

        try:
            stream = await self.client.chat.completions.create(**params)
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue

                choice = choices[0]
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason

                delta = getattr(choice, "delta", None)
                if not delta:
                    continue

                content_delta = getattr(delta, "content", None)
                if content_delta:
                    full_content += content_delta
                    await self._emit_stream_callback(full_content)

                reasoning_delta = getattr(delta, "reasoning_content", None)
                if reasoning_delta:
                    thinking_content += reasoning_delta

                reasoning_details = getattr(delta, "reasoning_details", None)
                if reasoning_details:
                    for detail in reasoning_details:
                        text = getattr(detail, "text", None)
                        if text:
                            thinking_content += text

                for tool_call in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tool_call, "index", 0) or 0
                    part = tool_call_parts.setdefault(
                        index,
                        {"id": None, "type": "function", "name": "", "arguments": ""},
                    )
                    if getattr(tool_call, "id", None):
                        part["id"] = tool_call.id
                    if getattr(tool_call, "type", None):
                        part["type"] = tool_call.type

                    function = getattr(tool_call, "function", None)
                    if function:
                        if getattr(function, "name", None):
                            part["name"] += function.name
                        if getattr(function, "arguments", None):
                            part["arguments"] += function.arguments

            tool_calls = []
            for index, part in sorted(tool_call_parts.items()):
                if not part["name"]:
                    continue
                try:
                    arguments = json.loads(part["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}

                tool_calls.append(
                    ToolCall(
                        id=part["id"] or f"call_{index}",
                        type=part["type"] or "function",
                        function=FunctionCall(
                            name=part["name"],
                            arguments=arguments,
                        ),
                    )
                )

            return LLMResponse(
                content=full_content,
                thinking=thinking_content if thinking_content else None,
                tool_calls=tool_calls if tool_calls else None,
                finish_reason=finish_reason or "stop",
                usage=None,
            )
        except Exception as e:
            setattr(e, "_stream_emitted", bool(full_content))
            raise

    def _convert_tools(self, tools: list[Any]) -> list[dict[str, Any]]:
        """Convert tools to OpenAI format.

        Args:
            tools: List of Tool objects or dicts

        Returns:
            List of tools in OpenAI dict format
        """
        result = []
        for tool in tools:
            if isinstance(tool, dict):
                # If already a dict, check if it's in OpenAI format
                if "type" in tool and tool["type"] == "function":
                    result.append(tool)
                else:
                    # Assume it's in Anthropic format, convert to OpenAI
                    result.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool["description"],
                                "parameters": tool["input_schema"],
                            },
                        }
                    )
            elif hasattr(tool, "to_openai_schema"):
                # Tool object with to_openai_schema method
                result.append(tool.to_openai_schema())
            else:
                raise TypeError(f"Unsupported tool type: {type(tool)}")
        return result

    def _convert_content(self, content: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        """Convert internal multimodal content blocks to OpenAI chat format."""
        if not isinstance(content, list):
            return content

        converted: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "text":
                converted.append({"type": "text", "text": block.get("text", "")})
                continue

            if block_type == "image":
                source = block.get("source") or {}
                if isinstance(source, dict):
                    media_type = source.get("media_type") or source.get("mediaType") or "image/png"
                    data = source.get("data")
                    if data:
                        converted.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{data}",
                                },
                            }
                        )
                continue

            converted.append(block)

        return converted

    def _convert_messages(self, messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert internal messages to OpenAI format.

        Args:
            messages: List of internal Message objects

        Returns:
            Tuple of (system_message, api_messages)
            Note: OpenAI includes system message in the messages array
        """
        api_messages = []

        for msg in messages:
            if msg.role == "system":
                # OpenAI includes system message in messages array
                api_messages.append({"role": "system", "content": msg.content})
                continue

            # For user messages
            if msg.role == "user":
                api_messages.append({"role": "user", "content": self._convert_content(msg.content)})

            # For assistant messages
            elif msg.role == "assistant":
                assistant_msg = {"role": "assistant"}

                # Add content if present
                if msg.content:
                    assistant_msg["content"] = msg.content

                # Add tool calls if present
                if msg.tool_calls:
                    tool_calls_list = []
                    for tool_call in msg.tool_calls:
                        tool_calls_list.append(
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": json.dumps(tool_call.function.arguments),
                                },
                            }
                        )
                    assistant_msg["tool_calls"] = tool_calls_list

                # IMPORTANT: Add reasoning_details if thinking is present
                # This is CRITICAL for Interleaved Thinking to work properly!
                # The complete response_message (including reasoning_details) must be
                # preserved in Message History and passed back to the model in the next turn.
                # This ensures the model's chain of thought is not interrupted.
                if msg.thinking:
                    assistant_msg["reasoning_details"] = [{"text": msg.thinking}]

                api_messages.append(assistant_msg)

            # For tool result messages
            elif msg.role == "tool":
                api_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )

        return None, api_messages

    def _prepare_request(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Prepare the request for OpenAI API.

        Args:
            messages: List of conversation messages
            tools: Optional list of available tools

        Returns:
            Dictionary containing request parameters
        """
        _, api_messages = self._convert_messages(messages)

        return {
            "api_messages": api_messages,
            "tools": tools,
        }

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse OpenAI response into LLMResponse.

        Args:
            response: OpenAI ChatCompletion response (full response object)

        Returns:
            LLMResponse object
        """
        # Get message from response
        message = response.choices[0].message

        # Debug: Log message attributes
        logger.info(f"[OpenAI] Message attributes: {dir(message)}")
        logger.info(f"[OpenAI] Has reasoning_details: {hasattr(message, 'reasoning_details')}")
        logger.info(f"[OpenAI] Has reasoning_content: {hasattr(message, 'reasoning_content')}")
        if hasattr(message, "reasoning_details"):
            logger.info(f"[OpenAI] reasoning_details: {message.reasoning_details}")
        if hasattr(message, "reasoning_content"):
            logger.info(f"[OpenAI] reasoning_content: {message.reasoning_content[:200] if message.reasoning_content else 'None'}...")

        # Extract text content
        text_content = message.content or ""

        # Extract thinking content from multiple possible fields
        thinking_content = ""
        
        # Try reasoning_details first (MiniMax M2.5 format)
        if hasattr(message, "reasoning_details") and message.reasoning_details:
            # reasoning_details is a list of reasoning blocks
            for detail in message.reasoning_details:
                if hasattr(detail, "text"):
                    thinking_content += detail.text
        
        # Try reasoning_content (alternative field name)
        if not thinking_content and hasattr(message, "reasoning_content") and message.reasoning_content:
            thinking_content = message.reasoning_content
        
        # Debug: Log extracted thinking
        logger.info(f"[OpenAI] Extracted thinking content: {thinking_content[:100] if thinking_content else 'None'}...")

        # Extract tool calls
        tool_calls = []
        if message.tool_calls:
            for tool_call in message.tool_calls:
                # Parse arguments from JSON string
                arguments = json.loads(tool_call.function.arguments)

                tool_calls.append(
                    ToolCall(
                        id=tool_call.id,
                        type="function",
                        function=FunctionCall(
                            name=tool_call.function.name,
                            arguments=arguments,
                        ),
                    )
                )

        # Extract token usage from response
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        return LLMResponse(
            content=text_content,
            thinking=thinking_content if thinking_content else None,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason="stop",  # OpenAI doesn't provide finish_reason in the message
            usage=usage,
        )

    async def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> LLMResponse:
        """Generate response from OpenAI LLM.

        Args:
            messages: List of conversation messages
            tools: Optional list of available tools

        Returns:
            LLMResponse containing the generated content
        """
        # Prepare request
        request_params = self._prepare_request(messages, tools)

        # Streaming path: emit incremental content updates while keeping the
        # existing final-response parsing logic for tool calls and usage data.
        if self.stream_callback:
            if self.retry_config.enabled:
                for attempt in range(self.retry_config.max_retries + 1):
                    try:
                        response = await self._make_stream_api_request(
                            request_params["api_messages"],
                            request_params["tools"],
                        )
                        return response
                    except Exception as e:
                        if getattr(e, "_stream_emitted", False):
                            raise

                        if attempt >= self.retry_config.max_retries:
                            from ..retry import RetryExhaustedError

                            raise RetryExhaustedError(e, attempt + 1)

                        delay = self.retry_config.calculate_delay(attempt)
                        logger.warning(
                            "Streaming request failed: %s, retrying attempt %s after %.2f seconds",
                            str(e),
                            attempt + 2,
                            delay,
                        )
                        if self.retry_callback:
                            self.retry_callback(e, attempt + 1)
                        await asyncio.sleep(delay)
            else:
                response = await self._make_stream_api_request(
                    request_params["api_messages"],
                    request_params["tools"],
                )
                return response

        # Make API request with retry logic
        if self.retry_config.enabled:
            # Apply retry logic
            retry_decorator = async_retry(config=self.retry_config, on_retry=self.retry_callback)
            api_call = retry_decorator(self._make_api_request)
            response = await api_call(
                request_params["api_messages"],
                request_params["tools"],
            )
        else:
            # Don't use retry
            response = await self._make_api_request(
                request_params["api_messages"],
                request_params["tools"],
            )

        # Parse and return response
        return self._parse_response(response)
