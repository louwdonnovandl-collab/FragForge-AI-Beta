FF GitHub 046 - Mr Director fallback GitHub patch

This is a source patch, NOT the full editor or a complete EXE fix.

Upload into the ROOT of your existing FragForge repository:
  director_plan_fallback.py
  tests/test_director_plan_fallback.py
  .github/workflows/director-fallback-tests.yml

In GitHub: Code > Add file > Upload files, upload the Python files to their
respective folders (GitHub web upload may not preserve folder structure;
create the folders/files manually if needed). Commit to main.

The separate 'Test Mr Director fallback' action runs seven unit tests on Windows.
It does not alter your existing 'Build FragForge Windows' workflow.

IMPORTANT: To fix the error INSIDE the app, you must integrate this function
into the current Mr Director Ollama caller:

    from director_plan_fallback import generate_director_plan
    plan = generate_director_plan(user_request)
    if plan['source'] == 'fallback':
        # Show plan['warning'] in the GUI; require user approval.
        pass

The returned 'steps' are suggestions, NOT your app's existing edit-plan schema.
Map them into your app's existing action format before execution.

If you send the latest source files or repository URL, I can prepare the exact
integration change and update the existing build workflow.
