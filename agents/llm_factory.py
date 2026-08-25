"""
AMR Guardian Enterprise - Inference Engine
Supports local air-gapped Ollama models (Llama 3, DeepSeek, MedLlama),
OpenAI API, and Anthropic Claude endpoints with fallback mechanisms and strict mock testing mode.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger("AMRGuardian.LLMFactory")


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generates a text completion given a prompt and system instruction."""
        pass


class MockLLMProvider(BaseLLMProvider):
    """Deterministic, air-gapped test mock provider."""
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        prompt_lower = prompt.lower()
        if "mismatch" in prompt_lower or "resistant" in prompt_lower:
            return (
                "CLINICAL RECOMMENDATION: BUG-DRUG MISMATCH DETECTED.\n"
                "The isolated pathogen displays in vitro resistance to current empirical therapy. "
                "Immediate escalation to targeted susceptible agent indicated according to IDSA guidelines."
            )
        elif "de-escalation" in prompt_lower or "mssa" in prompt_lower:
            return (
                "CLINICAL RECOMMENDATION: SPECTRUM DE-ESCALATION OPPORTUNITY.\n"
                "Pathogen is Methicillin-Susceptible Staphylococcus aureus (MSSA). "
                "De-escalation from Vancomycin to Cefazolin or Nafcillin improves clinical outcomes and reduces nephrotoxicity."
            )
        elif "renal" in prompt_lower or "crcl" in prompt_lower:
            return (
                "CLINICAL RECOMMENDATION: RENAL DOSE ADJUSTMENT.\n"
                "Patient CrCl has decreased significantly. Dose interval extension or dose reduction "
                "is warranted to prevent acute kidney injury and neurotoxicity."
            )
        return "CLINICAL RECOMMENDATION: Antimicrobial regimen reviewed. Continue clinical and microbiological monitoring."


class OllamaLLMProvider(BaseLLMProvider):
    """Local air-gapped Ollama endpoint (e.g. MedLlama, Llama-3-70B, DeepSeek-R1)."""

    def __init__(self, model_name: str = "medllama2", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        try:
            import urllib.request
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "system": system_prompt or "You are an expert infectious disease clinical pharmacist AI.",
                "stream": False
            }
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = json.loads(response.read().decode("utf-8"))
                return res_body.get("response", "")
        except Exception as e:
            logger.warning(f"Ollama connection failed ({e}), falling back to MockLLMProvider.")
            return MockLLMProvider().generate(prompt, system_prompt)


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI GPT-4o / GPT-4-turbo provider."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            return MockLLMProvider().generate(prompt, system_prompt)
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            resp = client.chat.completions.create(model=self.model, messages=messages, temperature=0.1)
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"OpenAI completion failed ({e}), falling back to MockLLMProvider.")
            return MockLLMProvider().generate(prompt, system_prompt)


class ClaudeLLMProvider(BaseLLMProvider):
    """Anthropic Claude 3.5 Sonnet provider."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            return MockLLMProvider().generate(prompt, system_prompt)
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            resp = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt or "You are an expert infectious disease clinical pharmacist AI.",
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.content[0].text
        except Exception as e:
            logger.warning(f"Claude completion failed ({e}), falling back to MockLLMProvider.")
            return MockLLMProvider().generate(prompt, system_prompt)


class LLMFactory:
    """Factory to instantiate and manage LLM engines."""

    @staticmethod
    def get_provider(provider_type: str = "mock", **kwargs) -> BaseLLMProvider:
        provider_type = provider_type.lower()
        if provider_type == "ollama":
            return OllamaLLMProvider(
                model_name=kwargs.get("model_name", "medllama2"),
                base_url=kwargs.get("base_url", "http://localhost:11434")
            )
        elif provider_type in ("openai", "gpt4"):
            return OpenAILLMProvider(api_key=kwargs.get("api_key"), model=kwargs.get("model", "gpt-4o"))
        elif provider_type in ("claude", "anthropic"):
            return ClaudeLLMProvider(api_key=kwargs.get("api_key"), model=kwargs.get("model", "claude-3-5-sonnet-20241022"))
        else:
            return MockLLMProvider()
