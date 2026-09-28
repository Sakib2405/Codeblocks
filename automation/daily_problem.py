import json
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

REPO_DIR = Path(r"D:\CodeblocksRepo")
PROBLEMS_DIR = REPO_DIR / "problems"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5-coder:1.5b"

GPP = "g++"

MAX_EXISTING_PROBLEMS = 30


# ============================================================
# BASIC HELPERS
# ============================================================

def log(message):
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    )


def run_command(command, cwd=None, capture=True):

    log(
        "Running: " +
        " ".join(str(x) for x in command)
    )

    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=capture,
        encoding="utf-8",
        errors="replace"
    )


def clean_code_fence(text):

    text = text.strip()

    if text.startswith("```"):

        lines = text.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines)

    return text.strip()


def slugify(text):

    text = text.lower().strip()

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text
    )

    text = text.strip("-")

    if not text:
        text = "daily-problem"

    return text[:80]


# ============================================================
# CHECK ENVIRONMENT
# ============================================================

def check_environment():

    log("Checking environment...")

    if not REPO_DIR.exists():

        raise RuntimeError(
            f"Repository not found:\n{REPO_DIR}"
        )

    if not (REPO_DIR / ".git").exists():

        raise RuntimeError(
            "This folder is not a Git repository:\n"
            f"{REPO_DIR}"
        )

    PROBLEMS_DIR.mkdir(
        exist_ok=True
    )

    log(
        f"Python: {sys.version.split()[0]}"
    )

    # Check g++
    try:

        result = run_command(
            [GPP, "--version"]
        )

        if result.returncode != 0:

            raise RuntimeError(
                result.stderr
            )

        lines = result.stdout.splitlines()

        if lines:
            log(
                "Compiler: " + lines[0]
            )

    except FileNotFoundError:

        raise RuntimeError(
            "g++ was not found.\n"
            "Make sure g++ is installed and available in PATH."
        )

    # Check Ollama
    try:

        result = run_command(
            ["ollama", "--version"]
        )

        if result.returncode == 0:

            log(
                "Ollama: " +
                result.stdout.strip()
            )

    except FileNotFoundError:

        raise RuntimeError(
            "Ollama was not found in PATH."
        )


# ============================================================
# GIT SYNC
# ============================================================

def git_sync():

    log("Checking Git status...")

    result = run_command(
        [
            "git",
            "status",
            "--porcelain"
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Unable to read Git status.\n" +
            result.stderr
        )

    if result.stdout.strip():

        raise RuntimeError(
            "Your repository has uncommitted changes.\n\n"
            "Please commit or stash them before running "
            "the automatic generator.\n\n"
            "Changed files:\n" +
            result.stdout
        )

    log("Pulling latest changes...")

    result = run_command(
        [
            "git",
            "pull",
            "--ff-only",
            "origin",
            "main"
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Git pull failed.\n\n" +
            result.stdout +
            "\n" +
            result.stderr
        )

    log("Git repository is up to date.")


# ============================================================
# READ EXISTING PROBLEMS
# ============================================================

def get_existing_problems():

    existing = []

    if not PROBLEMS_DIR.exists():
        return existing

    folders = sorted(
        [
            p
            for p in PROBLEMS_DIR.iterdir()
            if p.is_dir()
        ],
        key=lambda x: x.name.lower()
    )

    for folder in folders[
        -MAX_EXISTING_PROBLEMS:
    ]:

        problem_file = folder / "problem.md"

        if not problem_file.exists():
            continue

        try:

            content = problem_file.read_text(
                encoding="utf-8"
            )

            existing.append(
                {
                    "folder": folder.name,
                    "content": content[:3000]
                }
            )

        except Exception:
            pass

    return existing


def build_existing_summary():

    problems = get_existing_problems()

    if not problems:

        return (
            "No previous generated problems exist."
        )

    parts = []

    for item in problems:

        parts.append(
            "Folder: " +
            item["folder"] +
            "\n" +
            item["content"]
        )

    return "\n\n---\n\n".join(parts)


# ============================================================
# OLLAMA
# ============================================================

def call_ollama(prompt):

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.7,
            "num_ctx": 4096
        }
    }

    data = json.dumps(
        payload
    ).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=600
        ) as response:

            raw = response.read().decode(
                "utf-8",
                errors="replace"
            )

    except urllib.error.URLError as e:

        raise RuntimeError(
            "Could not connect to Ollama.\n\n"
            "Make sure Ollama is running.\n\n"
            f"Error: {e}"
        )

    except Exception as e:

        raise RuntimeError(
            f"Ollama request failed:\n{e}"
        )

    try:

        response_json = json.loads(raw)

    except json.JSONDecodeError:

        raise RuntimeError(
            "Ollama returned invalid response:\n\n" +
            raw[:2000]
        )

    model_output = response_json.get(
        "response",
        ""
    )

    if not model_output:

        raise RuntimeError(
            "Ollama returned an empty response."
        )

    return model_output


# ============================================================
# GENERATE PROBLEM
# ============================================================

def generate_problem():

    existing_summary = (
        build_existing_summary()
    )

    prompt = f"""
You are an expert competitive programming problem setter.

Generate EXACTLY ONE new original C++ programming problem.

The problem must be suitable for a beginner/intermediate
competitive programming repository.

IMPORTANT:
- Do NOT copy an existing problem.
- Do NOT create a problem with the same core idea as an existing one.
- Use a different algorithmic concept when possible.
- The problem must be solvable using standard C++17.
- Avoid external libraries.
- Avoid advanced mathematics unless clearly explained.
- Make the examples correct.
- Make the solution correct.
- Make constraints consistent with the intended algorithm.
- Do not require interactive input.
- Do not require files.
- Do not use floating point unless absolutely necessary.

Return ONLY valid JSON.

Required JSON structure:

{{
  "title": "Problem title",
  "difficulty": "Easy/Medium/Hard",
  "statement": "Complete problem statement",
  "input": "Input format",
  "output": "Output format",
  "constraints": [
    "constraint 1",
    "constraint 2"
  ],
  "examples": [
    {{
      "input": "sample input",
      "output": "sample output",
      "explanation": "short explanation"
    }}
  ],
  "approach": "Explain the algorithm clearly",
  "complexity": "Time and space complexity",
  "solution_cpp": "Complete C++17 solution"
}}

The solution_cpp field must contain ONLY C++ source code.

Here are some recently generated problems.
Avoid duplicates:

{existing_summary}
"""

    log(
        "Asking Ollama to generate a new problem..."
    )

    raw = call_ollama(prompt)

    raw = raw.strip()

    raw = clean_code_fence(raw)

    try:

        problem = json.loads(raw)

    except json.JSONDecodeError as e:

        start = raw.find("{")
        end = raw.rfind("}")

        if (
            start != -1
            and end != -1
            and end > start
        ):

            possible_json = raw[
                start:end + 1
            ]

            try:

                problem = json.loads(
                    possible_json
                )

            except json.JSONDecodeError:

                raise RuntimeError(
                    "AI returned invalid JSON.\n\n"
                    f"JSON error: {e}\n\n"
                    "AI output:\n" +
                    raw[:5000]
                )

        else:

            raise RuntimeError(
                "AI did not return valid JSON.\n\n"
                "AI output:\n" +
                raw[:5000]
            )

    required_fields = [
        "title",
        "difficulty",
        "statement",
        "input",
        "output",
        "constraints",
        "examples",
        "approach",
        "complexity",
        "solution_cpp"
    ]

    for field in required_fields:

        if field not in problem:

            raise RuntimeError(
                "AI response is missing field: " +
                field
            )

    if not isinstance(
        problem["examples"],
        list
    ):

        raise RuntimeError(
            "examples must be a list."
        )

    if len(problem["examples"]) == 0:

        raise RuntimeError(
            "At least one example is required."
        )

    if not str(
        problem["solution_cpp"]
    ).strip():

        raise RuntimeError(
            "AI generated an empty C++ solution."
        )

    problem["solution_cpp"] = (
        clean_code_fence(
            str(problem["solution_cpp"])
        )
    )

    return problem


# ============================================================
# CREATE FILES
# ============================================================

def get_unique_folder(title):

    base_slug = slugify(title)

    folder = PROBLEMS_DIR / base_slug

    counter = 2

    while folder.exists():

        folder = PROBLEMS_DIR / (
            f"{base_slug}-{counter}"
        )

        counter += 1

    return folder


def create_problem_files(problem):

    folder = get_unique_folder(
        problem["title"]
    )

    folder.mkdir(
        parents=True,
        exist_ok=False
    )

    problem_file = folder / "problem.md"

    solution_file = folder / "solution.cpp"

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    constraints = problem["constraints"]

    if isinstance(
        constraints,
        list
    ):

        constraints_text = "\n".join(
            "- " + str(item)
            for item in constraints
        )

    else:

        constraints_text = str(
            constraints
        )

    # --------------------------------------------------------
    # Examples
    # --------------------------------------------------------

    examples_text = []

    for index, example in enumerate(
        problem["examples"],
        start=1
    ):

        example_input = str(
            example.get(
                "input",
                ""
            )
        ).strip()

        example_output = str(
            example.get(
                "output",
                ""
            )
        ).strip()

        explanation = str(
            example.get(
                "explanation",
                ""
            )
        ).strip()

        example_block = (
            "### Example " +
            str(index) +
            "\n\n"
            "**Input**\n"
            "```text\n" +
            example_input +
            "\n```\n\n"
            "**Output**\n"
            "```text\n" +
            example_output +
            "\n```\n\n"
            "**Explanation**\n\n" +
            explanation +
            "\n"
        )

        examples_text.append(
            example_block
        )

    examples_block = "\n".join(
        examples_text
    )

    # --------------------------------------------------------
    # Markdown
    # --------------------------------------------------------

    markdown = (
        "# " +
        str(problem["title"]) +
        "\n\n"

        "**Difficulty:** " +
        str(problem["difficulty"]) +
        "\n\n"

        "## Problem Statement\n\n" +
        str(problem["statement"]) +
        "\n\n"

        "## Input\n\n" +
        str(problem["input"]) +
        "\n\n"

        "## Output\n\n" +
        str(problem["output"]) +
        "\n\n"

        "## Constraints\n\n" +
        constraints_text +
        "\n\n"

        "## Examples\n\n" +
        examples_block +
        "\n"

        "## Approach\n\n" +
        str(problem["approach"]) +
        "\n\n"

        "## Complexity\n\n" +
        str(problem["complexity"]) +
        "\n\n"

        "---\n\n"

        "Generated automatically using local Ollama AI.\n"
    )

    problem_file.write_text(
        markdown,
        encoding="utf-8"
    )

    solution_file.write_text(
        str(
            problem["solution_cpp"]
        ).strip() +
        "\n",
        encoding="utf-8"
    )

    log(
        "Created problem: " +
        folder.name
    )

    return folder


# ============================================================
# COMPILE SOLUTION
# ============================================================

def compile_solution(folder):

    solution_file = (
        folder / "solution.cpp"
    )

    exe_file = (
        folder / "solution.exe"
    )

    log(
        "Compiling solution..."
    )

    result = run_command(
        [
            GPP,
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            str(solution_file),
            "-o",
            str(exe_file)
        ],
        cwd=folder
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Compilation failed.\n\n"
            "STDOUT:\n" +
            result.stdout +
            "\n\n"
            "STDERR:\n" +
            result.stderr
        )

    log(
        "Compilation successful."
    )

    return exe_file


# ============================================================
# RUN SAMPLE TESTS
# ============================================================

def run_sample_tests(
    folder,
    problem
):

    exe_file = (
        folder / "solution.exe"
    )

    if not exe_file.exists():

        raise RuntimeError(
            "solution.exe was not created."
        )

    examples = problem["examples"]

    log(
        f"Running {len(examples)} sample test(s)..."
    )

    for index, example in enumerate(
        examples,
        start=1
    ):

        test_input = str(
            example.get(
                "input",
                ""
            )
        )

        expected_output = str(
            example.get(
                "output",
                ""
            )
        ).strip()

        try:

            result = subprocess.run(
                [str(exe_file)],
                input=test_input,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                cwd=str(folder)
            )

        except subprocess.TimeoutExpired:

            raise RuntimeError(
                f"Sample test {index} timed out."
            )

        if result.returncode != 0:

            raise RuntimeError(
                f"Sample test {index} crashed.\n\n"
                "STDOUT:\n" +
                result.stdout +
                "\n\n"
                "STDERR:\n" +
                result.stderr
            )

        actual_output = (
            result.stdout.strip()
        )

        if actual_output != expected_output:

            raise RuntimeError(
                f"Sample test {index} failed.\n\n"
                "Input:\n" +
                test_input +
                "\n\n"
                "Expected:\n" +
                expected_output +
                "\n\n"
                "Actual:\n" +
                actual_output
            )

        log(
            f"Sample {index}: PASS"
        )

    log(
        "All sample tests passed."
    )


# ============================================================
# REMOVE EXECUTABLE
# ============================================================

def remove_executable(folder):

    exe_file = (
        folder / "solution.exe"
    )

    if exe_file.exists():

        try:

            exe_file.unlink()

            log(
                "Removed temporary solution.exe"
            )

        except Exception as e:

            log(
                "Warning: could not remove "
                f"solution.exe: {e}"
            )


# ============================================================
# GIT VALIDATION
# ============================================================

def git_check_generated_files(
    folder
):

    relative_folder = (
        folder.relative_to(REPO_DIR)
    )

    log(
        "Checking Git changes..."
    )

    result = run_command(
        [
            "git",
            "status",
            "--short"
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Could not check Git status."
        )

    changed = result.stdout.strip()

    if not changed:

        raise RuntimeError(
            "No Git changes detected."
        )

    print()
    print("Git changes:")
    print(changed)

    expected_prefix = str(
        relative_folder
    ).replace("\\", "/")

    unexpected = []

    for line in changed.splitlines():

        if len(line) < 4:
            continue

        path = line[3:].strip()

        path = path.replace(
            "\\",
            "/"
        )

        if not path.startswith(
            expected_prefix + "/"
        ):

            unexpected.append(path)

    if unexpected:

        raise RuntimeError(
            "Unexpected files were modified.\n\n" +
            "\n".join(unexpected)
        )


# ============================================================
# GIT COMMIT + PUSH
# ============================================================

def git_commit_and_push(
    folder,
    problem
):

    relative_folder = (
        folder.relative_to(REPO_DIR)
    )

    relative_folder_string = str(
        relative_folder
    ).replace(
        "\\",
        "/"
    )

    log(
        "Adding generated problem to Git..."
    )

    result = run_command(
        [
            "git",
            "add",
            "--",
            relative_folder_string
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "git add failed.\n" +
            result.stderr
        )

    result = run_command(
        [
            "git",
            "diff",
            "--cached",
            "--name-only"
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Could not inspect staged files."
        )

    staged_files = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    if not staged_files:

        raise RuntimeError(
            "Nothing was staged."
        )

    print()
    print("Staged files:")

    for file in staged_files:
        print(
            "  " + file
        )

    for file in staged_files:

        normalized = file.replace(
            "\\",
            "/"
        )

        if not normalized.startswith(
            relative_folder_string + "/"
        ):

            raise RuntimeError(
                "Safety check failed.\n"
                "An unexpected file was staged:\n" +
                file
            )

    commit_message = (
        "daily: add " +
        slugify(
            problem["title"]
        ) +
        " problem"
    )

    log(
        "Creating commit..."
    )

    result = run_command(
        [
            "git",
            "commit",
            "-m",
            commit_message
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "git commit failed.\n\n" +
            result.stdout +
            "\n" +
            result.stderr
        )

    log(
        "Commit created."
    )

    log(
        "Pushing to GitHub..."
    )

    result = run_command(
        [
            "git",
            "push",
            "origin",
            "main"
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "git push failed.\n\n" +
            result.stdout +
            "\n" +
            result.stderr
        )

    log(
        "Push successful."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    generated_folder = None

    try:

        print()
        print("=" * 60)
        print(
            "        DAILY C++ PROBLEM GENERATOR"
        )
        print("=" * 60)
        print()

        check_environment()

        git_sync()

        problem = generate_problem()

        print()
        print(
            "Generated:"
        )
        print(
            "Title:",
            problem["title"]
        )
        print(
            "Difficulty:",
            problem["difficulty"]
        )
        print()

        generated_folder = (
            create_problem_files(
                problem
            )
        )

        compile_solution(
            generated_folder
        )

        run_sample_tests(
            generated_folder,
            problem
        )

        remove_executable(
            generated_folder
        )

        git_check_generated_files(
            generated_folder
        )

        git_commit_and_push(
            generated_folder,
            problem
        )

        print()
        print("=" * 60)
        print(
            "SUCCESS"
        )
        print("=" * 60)
        print()

        print(
            "Problem added:",
            problem["title"]
        )

        print(
            "Folder:",
            generated_folder
        )

        print()

        print(
            "The new problem has been compiled, "
            "tested, committed and pushed to GitHub."
        )

        print()

    except Exception as e:

        print()
        print("=" * 60)
        print(
            "FAILED"
        )
        print("=" * 60)
        print()

        print(
            str(e)
        )

        print()

        if (
            generated_folder
            and generated_folder.exists()
        ):

            try:

                remove_executable(
                    generated_folder
                )

                shutil.rmtree(
                    generated_folder
                )

                print(
                    "Generated problem was removed "
                    "because the process failed."
                )

            except Exception as cleanup_error:

                print(
                    "WARNING: Could not clean up "
                    "generated problem:"
                )

                print(
                    cleanup_error
                )

        sys.exit(1)


if __name__ == "__main__":
    main()