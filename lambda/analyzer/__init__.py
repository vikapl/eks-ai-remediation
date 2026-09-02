"""
analyzer package

Exposes one factory function, get_analyzer(), so handler.py never imports
MockAnalyzer or BedrockAnalyzer directly - it asks for "whatever AI_PROVIDER
says" and gets back something implementing the same IncidentAnalyzer
interface either way. This is the actual mechanism behind "swap in a real
LLM later without touching the handler."
"""
from analyzer.base import IncidentAnalyzer
from analyzer.mock_analyzer import MockAnalyzer


def get_analyzer(provider: str, *, bedrock_model_id: str = "", aws_region: str = "us-east-1") -> IncidentAnalyzer:
    if provider == "mock":
        return MockAnalyzer()

    if provider == "bedrock":
        # Imported lazily, inside the branch that needs it. boto3's
        # bedrock-runtime client isn't constructed - and doesn't need
        # Bedrock model access enabled - unless AI_PROVIDER is actually set
        # to "bedrock". Keeps the mock-only path (what I run locally)
        # completely free of any Bedrock dependency at runtime.
        from analyzer.bedrock_analyzer import BedrockAnalyzer

        return BedrockAnalyzer(model_id=bedrock_model_id, region=aws_region)

    raise ValueError(f"Unknown AI_PROVIDER: {provider!r} (expected 'mock' or 'bedrock')")
