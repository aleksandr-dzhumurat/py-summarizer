"""FastAPI application for GitHub repository summarizer."""

import json
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

from src.llm.llm_adapter import DeepSeekLLMAdapter
from src.llm.prompts import repo_summarizer_prompt
from src.py_summarizer.naive_skeleton import code_skeleton
from src.py_summarizer.utils import clone_repo, get_index, get_logger

logger = get_logger(__name__)

class SummarizeRequest(BaseModel):
    github_url: HttpUrl


class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str


# Initialize FastAPI app
app = FastAPI(
    title="GitHub Repository Summarizer",
    description="Analyze GitHub repositories and generate LLM-based summaries",
    version="0.1.0"
)


# NOTE: persistence via SQLite has been removed. This app schedules background
# tasks and logs results. If you need persistence, re-add a storage layer.


async def run_pipeline(task_id: str, repo_url: str) -> dict:
    """Execute the full analysis pipeline for a repository."""
    repo_path = None
    try:
        # Clone repository
        repo_path = await clone_repo(repo_url, timeout=180)
        logger.info(f"Cloned {repo_url} to {repo_path}")

        # Index files
        index = get_index(str(repo_path))
        logger.info(f"Indexed {len(index)} files")

        # Generate skeleton
        skeleton = code_skeleton(index, str(repo_path))
        logger.info("Generated code skeleton")

        # Generate LLM summary
        llm = DeepSeekLLMAdapter()
        prompt = repo_summarizer_prompt(skeleton)
        summary_text = await llm.call(prompt)

        try:
            summary = json.loads(summary_text)
        except json.JSONDecodeError:
            summary = {
                "summary": summary_text,
                "technologies": [],
                "structure": "Unable to parse structure"
            }

        logger.info("Generated LLM summary")
        logger.info(f"Task {task_id} completed successfully: {list(summary.keys()) if isinstance(summary, dict) else 'raw text'}")

        return summary

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        raise
    finally:
        # Clean up cloned repository
        if repo_path and repo_path.exists():
            import shutil
            shutil.rmtree(repo_path, ignore_errors=True)
            logger.info(f"Cleaned up {repo_path}")


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize_repo(request: SummarizeRequest) -> SummarizeResponse:
    """
    Analyze a GitHub repository and generate a summary.
    
    This endpoint queues a background task to analyze the repository.
    Use the returned task_id with the /info endpoint to check status and retrieve results.
    """
    repo_url = str(request.github_url)
    task_id = str(uuid.uuid4())
    
    # Validate GitHub URL
    if "github.com" not in repo_url:
        raise HTTPException(
            status_code=400,
            detail="Only GitHub URLs are supported"
        )
    
    # Run analysis synchronously and return results
    try:
        result = await run_pipeline(task_id, repo_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Extract text summary if result.summary is a JSON object, otherwise use as-is
    summary_value = result.get("summary", "No summary available")
    if isinstance(summary_value, dict):
        summary_value = summary_value.get("summary", "No summary available")

    return SummarizeResponse(
        summary=summary_value,
        technologies=result.get("technologies", []),
        structure=result.get("structure", "No structure information available"),
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
