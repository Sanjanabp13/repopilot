# RepoPilot

RepoPilot is a developer onboarding and repository-impact tool for Python codebases. It builds a repository map, traces call relationships, estimates blast radius for changes, and answers repository questions with local evidence and optional Gemini-backed generation.

## What RepoPilot does

- Parses Python source files into a symbol index
- Builds a call graph for function and method relationships
- Builds a dependency graph for imports and module coupling
- Highlights the downstream impact of changing a symbol
- Answers repository questions with citations from the indexed codebase
- Exports an ONBOARDING.md summary for onboarding and handoff

## Repository map and blast radius

The repository map is generated from the symbol and dependency graphs. Each node represents a symbol or module, and edges represent call or import relationships. Clicking a node computes the The repository map is generated from the symbol and dependency graphs. Each node represents a symbol or moduChatbot behavior

The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot The lThe lThe lot Thin time so a slow Gemini call does not block the API.

## Gemini configuration

Gemini is optional. The backend reads either `GEMINI_API_KEY` or `GOOGLE_API_KEY` from the repository-root `.env` file. Do not add the key to frontend code and do not commit the `.env` file.

Example `.env`:

```env
GEMINI_API_KEY=your_key_here
```

## Run## Run## Run## Run## Run## Run## Run## Run## Run## Run## R\Scripts\Activate.ps1
pip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip install -r requpip installyze `tests/fixtures/sample_project`.
3. Confirm the React Flow repository map loads.
4. Click a symbol such as `get_user` to compute blast radius.
5. Use the Back to Full Graph button to restore the full view.
6. Ask a question like: `What does get_user do and who calls it?`
7. Confirm the answer includes source citations.
8. E8. E8. E8. E8. E8.  to re8. E8. E8. E8. E8. E8.  to re8. E8. E8. E8. E8. E8.  to re8. E8. E8. E8. E8. E8.  to re8. E8. E8. E8. E8. E8.  to re8. E8. E8. E8. E8. E8.  to re8. E8. E8. E8. E8. E8.  to re8. E8. E8. E8requi8. E8. E8. E<<'EOF'
fastapi
uvicorn
pydantic
pathspecpaytest
google-generativeai
