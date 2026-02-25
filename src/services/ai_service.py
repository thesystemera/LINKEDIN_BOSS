import json
import re
import time
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel
from google import genai
from google.genai import types

from src.services.base_service import SingletonService
from src.config import settings
from src.utils.logger import custom_print

class _GeminiMessage:
    def __init__(self, content):
        self.content = content

class _GeminiChoice:
    def __init__(self, message):
        self.message = message

class _GeminiResponse:
    def __init__(self, content, is_structured=False):
        if is_structured:
            self.choices = [_GeminiChoice(_GeminiMessage(json.dumps(content)))]
            self.structured_data = content
        else:
            self.choices = [_GeminiChoice(_GeminiMessage(content))]

class AIService(SingletonService):
    def __init__(self):
        if self._initialized:
            return

        self.client = None
        self.gemini_configured = False
        self._initialized = True

    async def initialize(self):
        if self.gemini_configured:
            return

        gemini_api_key = settings.load_api_key_from_file("gemini_key")

        if gemini_api_key:
            self.client = genai.Client(api_key=gemini_api_key)
            self.gemini_configured = True
            custom_print("AI", "AIService initialized - Gemini configured")
        else:
            custom_print("ERROR", "Gemini API key not found")

    async def call_gemini_structured(
            self,
            prompt: str,
            response_schema: Type[BaseModel],
            model: str,
            temperature: float = None,
            system_instruction: str = None
    ) -> Optional[Dict[str, Any]]:

        if not self.client:
            await self.initialize()

        if temperature is None:
            temperature = settings.GEMINI_TEMPERATURE

        prompt_chars = len(prompt)
        system_chars = len(system_instruction) if system_instruction else 0
        total_chars = prompt_chars + system_chars

        custom_print("AI_INPUT", f"Model: {model} | Temp: {temperature} | Input: {total_chars} chars")
        custom_print("AI_INPUT", f"--- PROMPT ---\n{prompt}\n----------------")

        config_params = {
            "response_mime_type": "application/json",
            "temperature": temperature
        }

        final_system_instruction = system_instruction or ""
        if response_schema:
            final_system_instruction += "\n\nOutput strictly valid JSON."

        if final_system_instruction:
            config_params["system_instruction"] = final_system_instruction

        start_time = time.time()

        try:
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_params)
            )

            elapsed = time.time() - start_time

            result_str = response.text

            custom_print("AI_OUTPUT", f"--- RESPONSE ---\n{result_str}\n----------------")

            result = json.loads(result_str)

            custom_print("AI_TIMING", f"⏱ {model} completed in {elapsed:.2f}s | Output: {len(result_str)} chars")
            return result

        except Exception as e:
            custom_print("ERROR", f"AI Generation failed: {e}")
            try:
                if 'response' in locals() and hasattr(response, 'text') and response.text:
                    text = response.text
                else:
                    return None

                text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
                text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)
                text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)

                result = json.loads(text.strip())
                custom_print("AI", "Recovered JSON from fallback parsing")
                return result
            except Exception as parse_error:
                custom_print("ERROR", f"Could not parse AI response as JSON: {str(parse_error)[:200]}")
                return None

    async def generate(
            self,
            messages: list,
            model: str,
            temperature: float = None,
            max_tokens: int = None,
            response_schema: Type[BaseModel] = None
    ):
        system_instruction = None
        user_content = ""

        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            elif msg["role"] == "user":
                user_content = msg["content"]

        if temperature is None:
            temperature = settings.GEMINI_TEMPERATURE

        if response_schema:
            result = await self.call_gemini_structured(
                prompt=user_content,
                response_schema=response_schema,
                model=model,
                temperature=temperature,
                system_instruction=system_instruction
            )
            return _GeminiResponse(result, is_structured=True)

        response_text = await self.call_gemini(
            prompt=user_content,
            system_instruction=system_instruction,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return _GeminiResponse(response_text, is_structured=False)

    async def call_gemini(
            self,
            prompt: str,
            system_instruction: str = None,
            model: str = None,
            temperature: float = None,
            max_tokens: int = None
    ) -> str:
        if not self.client:
            await self.initialize()

        if model is None:
            model = settings.GEMINI_MODEL_FORMS
        if temperature is None:
            temperature = settings.GEMINI_TEMPERATURE
        if max_tokens is None:
            max_tokens = 2048

        custom_print("AI", f"Calling Gemini API for text generation: {model}")
        custom_print("AI_INPUT", f"--- PROMPT ---\n{prompt}\n----------------")

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction
        )

        response = await self.client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=config
        )

        custom_print("AI_OUTPUT", f"--- RESPONSE ---\n{response.text}\n----------------")

        custom_print("AI", "Text generation completed")
        return response.text

    async def call_gemini_with_tools(
            self,
            prompt: str,
            tools: list,
            tool_handlers: dict,
            response_schema: Type[BaseModel] = None,
            system_instruction: str = None,
            model: str = None,
            temperature: float = None,
            max_iterations: int = 5
    ) -> Dict[str, Any]:
        if not self.client:
            await self.initialize()

        if model is None:
            model = settings.GEMINI_MODEL_FORMS
        if temperature is None:
            temperature = settings.GEMINI_TEMPERATURE

        custom_print("AI", f"Calling Gemini with tools: {model}")
        custom_print("AI_INPUT", f"--- PROMPT ---\n{prompt}\n----------------")

        config_params = {
            "temperature": temperature,
            "tools": tools
        }

        if system_instruction:
            if response_schema:
                system_instruction += f"\n\nIMPORTANT: After using tools, you must return the final response as valid JSON."
            config_params["system_instruction"] = system_instruction

        config = types.GenerateContentConfig(**config_params)

        conversation = [{"role": "user", "parts": [{"text": prompt}]}]

        for iteration in range(max_iterations):
            custom_print("AI", f"Tool iteration {iteration + 1}/{max_iterations}")

            response = await self.client.aio.models.generate_content(
                model=model,
                contents=conversation,
                config=config
            )

            function_call_found = False
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        function_call_found = True
                        function_call = part.function_call
                        function_name = function_call.name
                        function_args = dict(function_call.args)

                        custom_print("AI", f"🔧 Gemini calling tool: {function_name}({function_args})")

                        if function_name in tool_handlers:
                            tool_result = await tool_handlers[function_name](**function_args)

                            result_str = str(tool_result)
                            custom_print("AI", f"Tool {function_name} returned: {len(result_str)} chars")

                            conversation.append({
                                "role": "model",
                                "parts": [{"function_call": function_call}]
                            })
                            conversation.append({
                                "role": "user",
                                "parts": [{
                                    "function_response": {
                                        "name": function_name,
                                        "response": tool_result
                                    }
                                }]
                            })
                        else:
                            raise ValueError(f"Unknown tool requested: {function_name}")
                        break

            if function_call_found:
                continue

            text_response = None
            if hasattr(response, 'text') and response.text:
                text_response = response.text

            if text_response:
                try:
                    cleaned_text = text_response.strip()
                    if "```" in cleaned_text:
                        cleaned_text = re.sub(r"^```json\s*", "", cleaned_text, flags=re.MULTILINE)
                        cleaned_text = re.sub(r"^```\s*", "", cleaned_text, flags=re.MULTILINE)
                        cleaned_text = re.sub(r"\s*```$", "", cleaned_text, flags=re.MULTILINE)

                    custom_print("AI_OUTPUT", f"--- RESPONSE ---\n{cleaned_text}\n----------------")
                    return json.loads(cleaned_text)
                except:
                    custom_print("AI_OUTPUT", f"--- RESPONSE (Text) ---\n{text_response}\n----------------")
                    return {"text": text_response}

            raise RuntimeError(f"Tool call loop exceeded {max_iterations} iterations without final response")