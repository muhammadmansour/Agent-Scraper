"""
Agentic layer — LLM-powered autonomous scraping agent.

Components:
    brain.py    → Gemini LLM client with function calling
    tools.py    → Tool definitions the LLM can invoke
    observer.py → State observation system
    memory.py   → Persistent agent memory
    prompts.py  → System prompt for the LLM
    loop.py     → Main observe → reason → act → learn cycle
"""
