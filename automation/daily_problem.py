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

MAIN_BRANCH = "main"

MAX_EXISTING_PROBLEMS = 30

TEST_TIMEOUT = 10

# Maximum number of AI repair attempts after a compile/test error
MAX_REPAIR_ATTEMPTS = 2


# ============================================================
# BASIC HELPERS
# ============================================================

def log(message):
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    )


def run_command(command, cwd=None, capture=True):
    """
    Run a command and return CompletedProcess.
    """

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
    """
    Remove markdown code fences if AI adds them.
    """

    if text is None:
        return ""

    text = str(text).strip()

    if text.startswith("```"):

        lines = text.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines)

    return text.strip()


def slugify(text):
    """
    Convert title into a safe folder name.
    """

    text = str(text).lower().strip()

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text
    )

    text = text.strip("-")

    if not text:
        text = "daily-problem"

    return text[:80]


def normalize_git_path(path_text):
    """
    Normalize Git path for comparison.
    """

    return (
        path_text
        .replace("\\", "/")
        .strip()
        .lstrip("./")
    )


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
            f"This folder is not a Git repository:\n"
            f"{REPO_DIR}"
        )

    PROBLEMS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Python
    # --------------------------------------------------------

    log(
        "Python: " +
        sys.version.split()[0]
    )

    # --------------------------------------------------------
    # g++
    # --------------------------------------------------------

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
                "Compiler: " +
                lines[0]
            )

    except FileNotFoundError:

        raise RuntimeError(
            "g++ was not found.\n\n"
            "Make sure g++ is installed "
            "and available in PATH."
        )

    # --------------------------------------------------------
    # Ollama
    # --------------------------------------------------------

    try:

        result = run_command(
            ["ollama", "--version"]
        )

        if result.returncode != 0:

            raise RuntimeError(
                "Ollama command failed.\n" +
                result.stderr
            )

        log(
            "Ollama: " +
            result.stdout.strip()
        )

    except FileNotFoundError:

        raise RuntimeError(
            "Ollama was not found in PATH."
        )


# ============================================================
# GIT
# ============================================================

def get_git_status():

    result = run_command(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all"
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Unable to read Git status.\n\n" +
            result.stderr
        )

    return result.stdout.strip()


def git_sync():

    log("Checking Git status...")

    status = get_git_status()

    if status:

        raise RuntimeError(
            "Your repository has uncommitted changes.\n\n"
            "Please commit or stash them before running "
            "the automatic generator.\n\n"
            "Changed files:\n" +
            status
        )

    log("Pulling latest changes...")

    result = run_command(
        [
            "git",
            "pull",
            "--ff-only",
            "origin",
            MAIN_BRANCH
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
# EXISTING PROBLEMS
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

    for folder in folders[-MAX_EXISTING_PROBLEMS:]:

        problem_file = (
            folder /
            "problem.md"
        )

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
            "Content-Type":
            "application/json"
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

        response_json = json.loads(
            raw
        )

    except json.JSONDecodeError:

        raise RuntimeError(
            "Ollama returned invalid response:\n\n" +
            raw[:3000]
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
# PARSE JSON
# ============================================================

def parse_json_response(raw):

    raw = clean_code_fence(
        raw
    )

    try:

        return json.loads(
            raw
        )

    except json.JSONDecodeError as first_error:

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

                return json.loads(
                    possible_json
                )

            except json.JSONDecodeError:

                raise RuntimeError(
                    "AI returned invalid JSON.\n\n"
                    f"JSON error: {first_error}\n\n"
                    "AI output:\n" +
                    raw[:5000]
                )

        raise RuntimeError(
            "AI did not return valid JSON.\n\n"
            "AI output:\n" +
            raw[:5000]
        )


# ============================================================
# VALIDATE GENERATED PROBLEM
# ============================================================

def validate_problem(problem):

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

    if not str(
        problem["title"]
    ).strip():

        raise RuntimeError(
            "Problem title is empty."
        )

    if not str(
        problem["statement"]
    ).strip():

        raise RuntimeError(
            "Problem statement is empty."
        )

    if not isinstance(
        problem["examples"],
        list
    ):

        raise RuntimeError(
            "examples must be a list."
        )

    if len(
        problem["examples"]
    ) == 0:

        raise RuntimeError(
            "At least one example is required."
        )

    solution = clean_code_fence(
        problem["solution_cpp"]
    )

    if not solution:

        raise RuntimeError(
            "AI generated an empty C++ solution."
        )

    problem["solution_cpp"] = solution

    # --------------------------------------------------------
    # Important C++ validation
    # --------------------------------------------------------

    if not re.search(
        r"\bmain\s*\(",
        solution
    ):

        raise RuntimeError(
            "Generated C++ solution does not "
            "contain a main() function."
        )

    # Prevent obvious GUI-only code.

    if (
        "WinMain(" in solution
        and not re.search(
            r"\bmain\s*\(",
            solution
        )
    ):

        raise RuntimeError(
            "Generated solution appears to use "
            "WinMain instead of main()."
        )

    return problem


# ============================================================
# GENERATE INITIAL PROBLEM
# ============================================================

def generate_problem():

    existing_summary = (
        build_existing_summary()
    )

    prompt = f"""
You are an expert competitive programming
problem setter.

Generate EXACTLY ONE new original C++ programming problem.

The problem should be suitable for a
beginner/intermediate competitive programming
repository.

IMPORTANT:

- Do NOT copy an existing problem.
- Do NOT create the same core algorithmic idea
  as an existing problem.
- Prefer a different algorithmic concept.
- Use standard C++17 only.
- No external libraries.
- No interactive input.
- No external files.
- Avoid unnecessary floating point.
- Make constraints match the intended algorithm.
- Make every sample correct.
- Make the C++ solution correct.
- The solution MUST contain:
    int main()
  or
    signed main()
- The program MUST be a normal console application.
- Do NOT use WinMain.
- Do NOT use Windows GUI APIs.
- The solution_cpp must be complete and compilable.

Return ONLY valid JSON.

Required structure:

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
    }},
    {{
      "input": "sample input",
      "output": "sample output",
      "explanation": "short explanation"
    }}
  ],
  "approach": "Explain the algorithm clearly",
  "complexity": "Time and space complexity",
  "solution_cpp": "Complete C++17 source code"
}}

The solution_cpp field must contain ONLY C++ source code.

Here are recently generated problems.
Avoid duplicate ideas:

{existing_summary}
"""

    log(
        "Asking Ollama to generate a new problem..."
    )

    raw = call_ollama(
        prompt
    )

    problem = parse_json_response(
        raw
    )

    validate_problem(
        problem
    )

    return problem


# ============================================================
# CREATE FILES
# ============================================================

def get_unique_folder(title):

    base_slug = slugify(
        title
    )

    folder = (
        PROBLEMS_DIR /
        base_slug
    )

    counter = 2

    while folder.exists():

        folder = (
            PROBLEMS_DIR /
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

    problem_file = (
        folder /
        "problem.md"
    )

    solution_file = (
        folder /
        "solution.cpp"
    )

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    constraints = (
        problem["constraints"]
    )

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

        if not isinstance(
            example,
            dict
        ):

            raise RuntimeError(
                "Each example must be an object."
            )

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

    examples_block = (
        "\n".join(
            examples_text
        )
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

        "Generated automatically using "
        "local Ollama AI.\n"
    )

    problem_file.write_text(
        markdown,
        encoding="utf-8"
    )

    solution_file.write_text(
        problem["solution_cpp"].strip() +
        "\n",
        encoding="utf-8"
    )

    log(
        "Created problem: " +
        folder.name
    )

    return folder


# ============================================================
# REPAIR PROMPT
# ============================================================

def repair_solution(
    problem,
    current_code,
    error_message,
    error_type
):

    prompt = f"""
You are repairing a C++17 competitive programming solution.

The problem is:

TITLE:
{problem["title"]}

STATEMENT:
{problem["statement"]}

INPUT:
{problem["input"]}

OUTPUT:
{problem["output"]}

CONSTRAINTS:
{problem["constraints"]}

EXAMPLES:
{json.dumps(problem["examples"], indent=2)}

CURRENT C++ CODE:

{current_code}

The current code has this {error_type}:

{error_message}

Fix the code.

IMPORTANT:

- Return ONLY valid JSON.
- The JSON must contain exactly one field:
  "solution_cpp"
- solution_cpp must contain ONLY C++17 source code.
- The program MUST contain int main() or signed main().
- Do NOT use WinMain.
- Do NOT use Windows GUI APIs.
- Do NOT use external libraries.
- Preserve the intended problem solution.
- Make the code compile with:
  g++ -std=c++17 -O2 -Wall -Wextra
- Fix the actual error instead of changing the problem.
- Keep the input/output format unchanged.
"""

    log(
        "Asking Ollama to repair the solution..."
    )

    raw = call_ollama(
        prompt
    )

    data = parse_json_response(
        raw
    )

    if "solution_cpp" not in data:

        raise RuntimeError(
            "Repair response did not contain "
            "solution_cpp."
        )

    repaired = clean_code_fence(
        data["solution_cpp"]
    )

    if not repaired:

        raise RuntimeError(
            "AI returned an empty repaired solution."
        )

    if not re.search(
        r"\bmain\s*\(",
        repaired
    ):

        raise RuntimeError(
            "Repaired solution does not contain main()."
        )

    return repaired


# ============================================================
# COMPILE
# ============================================================

def compile_solution(folder):

    solution_file = (
        folder /
        "solution.cpp"
    )

    executable = (
        folder /
        "solution.exe"
    )

    if not solution_file.exists():

        raise RuntimeError(
            "solution.cpp was not created."
        )

    if executable.exists():

        try:
            executable.unlink()
        except Exception:
            pass

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
            str(executable)
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        error = (
            result.stdout +
            "\n" +
            result.stderr
        ).strip()

        raise RuntimeError(
            "Compilation failed.\n\n" +
            error
        )

    log(
        "Compilation successful."
    )

    return executable


# ============================================================
# SAMPLE TEST
# ============================================================

def normalize_output(text):

    text = text.replace(
        "\r\n",
        "\n"
    )

    text = text.replace(
        "\r",
        "\n"
    )

    return text.strip()


def run_sample_test(
    executable,
    sample_input,
    expected_output,
    sample_number
):

    log(
        f"Sample {sample_number}: running..."
    )

    try:

        result = subprocess.run(

            [
                str(executable)
            ],

            input=sample_input,

            text=True,

            capture_output=True,

            encoding="utf-8",

            errors="replace",

            timeout=TEST_TIMEOUT,

            cwd=str(
                executable.parent
            )
        )

    except subprocess.TimeoutExpired:

        raise RuntimeError(
            f"Sample {sample_number} timed out "
            f"after {TEST_TIMEOUT} seconds."
        )

    if result.returncode != 0:

        raise RuntimeError(
            f"Sample {sample_number} program "
            "exited with an error.\n\n"
            "STDOUT:\n" +
            result.stdout +
            "\nSTDERR:\n" +
            result.stderr
        )

    actual = normalize_output(
        result.stdout
    )

    expected = normalize_output(
        expected_output
    )

    if actual != expected:

        raise RuntimeError(
            f"Sample {sample_number} failed.\n\n"
            "Expected:\n" +
            expected +
            "\n\n"
            "Actual:\n" +
            actual
        )

    log(
        f"Sample {sample_number}: PASS"
    )


def test_solution(
    folder,
    problem
):

    executable = compile_solution(
        folder
    )

    examples = problem[
        "examples"
    ]

    log(
        f"Running {len(examples)} "
        "sample test(s)..."
    )

    try:

        for index, example in enumerate(
            examples,
            start=1
        ):

            sample_input = str(
                example.get(
                    "input",
                    ""
                )
            )

            sample_output = str(
                example.get(
                    "output",
                    ""
                )
            )

            run_sample_test(
                executable,
                sample_input,
                sample_output,
                index
            )

        log(
            "All sample tests passed."
        )

    finally:

        if executable.exists():

            try:

                executable.unlink()

                log(
                    "Removed temporary solution.exe"
                )

            except Exception as e:

                log(
                    "Warning: could not remove "
                    f"{executable}: {e}"
                )


# ============================================================
# COMPILE + TEST + AUTOMATIC REPAIR
# ============================================================

def validate_and_repair_solution(
    folder,
    problem
):

    for attempt in range(
        MAX_REPAIR_ATTEMPTS + 1
    ):

        try:

            log(
                f"Validation attempt "
                f"{attempt + 1}/"
                f"{MAX_REPAIR_ATTEMPTS + 1}"
            )

            test_solution(
                folder,
                problem
            )

            return

        except RuntimeError as error:

            error_message = str(
                error
            )

            # No more repair attempts.

            if attempt >= MAX_REPAIR_ATTEMPTS:

                raise RuntimeError(
                    "Solution could not be "
                    "validated after "
                    f"{MAX_REPAIR_ATTEMPTS} "
                    "repair attempt(s).\n\n" +
                    error_message
                )

            log(
                "Validation failed."
            )

            log(
                "Attempting automatic AI repair..."
            )

            solution_file = (
                folder /
                "solution.cpp"
            )

            if not solution_file.exists():

                raise RuntimeError(
                    "solution.cpp disappeared "
                    "during validation."
                )

            current_code = (
                solution_file.read_text(
                    encoding="utf-8"
                )
            )

            if (
                "Compilation failed"
                in error_message
            ):

                error_type = (
                    "compilation error"
                )

            else:

                error_type = (
                    "sample test failure"
                )

            repaired_code = repair_solution(
                problem,
                current_code,
                error_message,
                error_type
            )

            solution_file.write_text(
                repaired_code.strip() +
                "\n",
                encoding="utf-8"
            )

            problem["solution_cpp"] = (
                repaired_code
            )

            log(
                "AI repair applied."
            )


# ============================================================
# GIT SAFETY
# ============================================================

def get_generated_relative_path(
    generated_folder
):

    try:

        relative = (
            generated_folder
            .relative_to(REPO_DIR)
        )

    except ValueError:

        raise RuntimeError(
            "Generated folder is outside "
            "the repository."
        )

    return normalize_git_path(
        str(relative)
    )


def is_path_inside(
    relative_path,
    parent_path
):

    relative_path = (
        normalize_git_path(
            relative_path
        )
    )

    parent_path = (
        normalize_git_path(
            parent_path
        )
    )

    if relative_path == parent_path:

        return True

    return relative_path.startswith(
        parent_path + "/"
    )


def validate_git_changes(
    generated_folder
):

    log(
        "Checking Git changes..."
    )

    status = get_git_status()

    if not status:

        raise RuntimeError(
            "Generated problem did not create "
            "any Git changes."
        )

    print()
    print("Git changes:")
    print(status)
    print()

    generated_relative = (
        get_generated_relative_path(
            generated_folder
        )
    )

    unexpected = []

    for line in status.splitlines():

        if not line.strip():
            continue

        if len(line) < 4:
            continue

        path_part = line[3:].strip()

        # Rename support

        if " -> " in path_part:

            path_part = (
                path_part.split(
                    " -> "
                )[-1]
            )

        path_part = normalize_git_path(
            path_part
        )

        if not is_path_inside(
            path_part,
            generated_relative
        ):

            unexpected.append(
                path_part
            )

    if unexpected:

        raise RuntimeError(
            "Unexpected files were modified.\n\n" +
            "\n".join(
                unexpected
            ) +
            "\n\n"
            "Only the newly generated "
            "problem folder may be modified."
        )

    log(
        "Git safety check passed."
    )


# ============================================================
# STAGE ONLY GENERATED FOLDER
# ============================================================

def stage_generated_problem(
    generated_folder
):

    generated_relative = (
        get_generated_relative_path(
            generated_folder
        )
    )

    log(
        "Staging generated problem only..."
    )

    result = run_command(
        [
            "git",
            "add",
            "--",
            generated_relative
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "git add failed.\n\n" +
            result.stdout +
            "\n" +
            result.stderr
        )

    # --------------------------------------------------------
    # Verify staged files
    # --------------------------------------------------------

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
            "Unable to inspect staged files."
        )

    staged_files = [

        normalize_git_path(line)

        for line in result.stdout.splitlines()

        if line.strip()
    ]

    if not staged_files:

        raise RuntimeError(
            "Nothing was staged."
        )

    unexpected = []

    for path in staged_files:

        if not is_path_inside(
            path,
            generated_relative
        ):

            unexpected.append(
                path
            )

    if unexpected:

        raise RuntimeError(
            "Safety check failed: "
            "unexpected files are staged.\n\n" +
            "\n".join(
                unexpected
            )
        )

    log(
        "Staged files:"
    )

    for path in staged_files:

        print(
            "  " + path
        )


# ============================================================
# COMMIT
# ============================================================

def commit_generated_problem(
    generated_folder
):

    slug = generated_folder.name

    commit_message = (
        "daily: add " +
        slug +
        " problem"
    )

    log(
        "Creating Git commit..."
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
            "Git commit failed.\n\n" +
            result.stdout +
            "\n" +
            result.stderr
        )

    log(
        "Git commit created."
    )


# ============================================================
# PUSH
# ============================================================

def push_changes():

    log(
        "Pushing to GitHub..."
    )

    result = run_command(
        [
            "git",
            "push",
            "origin",
            MAIN_BRANCH
        ],
        cwd=REPO_DIR
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Git push failed.\n\n" +
            result.stdout +
            "\n" +
            result.stderr
        )

    log(
        "GitHub push successful."
    )


# ============================================================
# CLEANUP
# ============================================================

def remove_generated_folder(
    generated_folder
):

    if generated_folder is None:
        return

    if not generated_folder.exists():
        return

    try:

        shutil.rmtree(
            generated_folder
        )

        log(
            "Generated problem was removed "
            "because the process failed."
        )

    except Exception as e:

        log(
            "Warning: could not remove "
            f"generated problem: {e}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    generated_folder = None

    print()
    print("=" * 60)
    print(
        "        DAILY C++ PROBLEM GENERATOR"
    )
    print("=" * 60)
    print()

    try:

        # ----------------------------------------------------
        # 1. Environment
        # ----------------------------------------------------

        check_environment()

        # ----------------------------------------------------
        # 2. Git sync
        # ----------------------------------------------------

        git_sync()

        # ----------------------------------------------------
        # 3. Generate problem
        # ----------------------------------------------------

        problem = generate_problem()

        print()
        print("Generated:")

        print(
            "Title: " +
            str(problem["title"])
        )

        print(
            "Difficulty: " +
            str(problem["difficulty"])
        )

        print()

        # ----------------------------------------------------
        # 4. Create files
        # ----------------------------------------------------

        generated_folder = (
            create_problem_files(
                problem
            )
        )

        # ----------------------------------------------------
        # 5. Compile + test + repair
        # ----------------------------------------------------

        validate_and_repair_solution(
            generated_folder,
            problem
        )

        # ----------------------------------------------------
        # 6. Git safety
        # ----------------------------------------------------

        validate_git_changes(
            generated_folder
        )

        # ----------------------------------------------------
        # 7. Stage only generated folder
        # ----------------------------------------------------

        stage_generated_problem(
            generated_folder
        )

        # ----------------------------------------------------
        # 8. Commit
        # ----------------------------------------------------

        commit_generated_problem(
            generated_folder
        )

        # ----------------------------------------------------
        # 9. Push
        # ----------------------------------------------------

        push_changes()

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        print()
        print("=" * 60)
        print(
            "                    SUCCESS"
        )
        print("=" * 60)
        print()

        print(
            "Problem: " +
            generated_folder.name
        )

        print(
            "Location: " +
            str(generated_folder)
        )

        print()

        print(
            "The new problem was generated, "
            "validated, tested, committed, "
            "and pushed to GitHub."
        )

        print()

        return 0

    except KeyboardInterrupt:

        print()

        print(
            "Process interrupted by user."
        )

        if generated_folder:

            remove_generated_folder(
                generated_folder
            )

        return 1

    except Exception as e:

        print()
        print("=" * 60)
        print(
            "                     FAILED"
        )
        print("=" * 60)
        print()

        print(
            str(e)
        )

        print()

        if generated_folder:

            remove_generated_folder(
                generated_folder
            )

        return 1


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )