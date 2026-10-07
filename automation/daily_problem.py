import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime


# ============================================================
# CONFIG
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = Path(
    os.environ.get(
        "DAILY_PROBLEM_REPO_DIR",
        str(SCRIPT_DIR.parent)
    )
).resolve()

PROBLEMS_SUBDIR = (
    os.environ.get(
        "DAILY_PROBLEM_TARGET_SUBDIR",
        "problems"
    ).strip() or "problems"
)

PROBLEMS_DIR = REPO_DIR / PROBLEMS_SUBDIR

OLLAMA_URL = os.environ.get(
    "DAILY_PROBLEM_OLLAMA_URL",
    "http://localhost:11434/api/generate"
).strip()

OLLAMA_MODEL = os.environ.get(
    "DAILY_PROBLEM_OLLAMA_MODEL",
    "qwen2.5-coder:1.5b"
).strip()

OLLAMA_API_KEY = os.environ.get(
    "DAILY_PROBLEM_OLLAMA_API_KEY",
    ""
).strip()

GPP = os.environ.get("DAILY_PROBLEM_GPP", "g++")
MAIN_BRANCH = os.environ.get("DAILY_PROBLEM_MAIN_BRANCH", "main")

SKIP_GIT_SYNC = os.environ.get(
    "DAILY_PROBLEM_SKIP_GIT_SYNC",
    "0"
).lower() in {"1", "true", "yes"}

SKIP_GIT_COMMIT = os.environ.get(
    "DAILY_PROBLEM_SKIP_GIT_COMMIT",
    "0"
).lower() in {"1", "true", "yes"}

SKIP_GIT_PUSH = os.environ.get(
    "DAILY_PROBLEM_SKIP_GIT_PUSH",
    "0"
).lower() in {"1", "true", "yes"}

TEST_TIMEOUT = 10
OLLAMA_TIMEOUT = 180

MAX_EXISTING_PROBLEMS = 30

# Repair attempts
MAX_REPAIR_ATTEMPTS = 2

# If repair fails, generate a completely new solution
MAX_REGENERATION_ATTEMPTS = 2


# ============================================================
# LOG
# ============================================================

def log(message):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")


# ============================================================
# COMMAND
# ============================================================

def run_command(command, cwd=REPO_DIR, timeout=120):
    log("Running: " + " ".join(str(x) for x in command))

    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip())

    return result


# ============================================================
# ENVIRONMENT
# ============================================================

def check_environment():
    log("Checking environment...")

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Python: {sys.version.split()[0]}"
    )

    result = run_command([GPP, "--version"])

    if result.returncode != 0:
        raise RuntimeError("g++ was not found.")

    lines = result.stdout.splitlines()

    if lines:
        log(f"Compiler: {lines[0]}")

    if not OLLAMA_MODEL:
        raise RuntimeError(
            "DAILY_PROBLEM_OLLAMA_MODEL is empty."
        )

    parsed = urllib.parse.urlparse(OLLAMA_URL)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            "DAILY_PROBLEM_OLLAMA_URL is invalid. "
            "Use a full URL like "
            "http://host:port/api/generate"
        )

    headers = {}

    if OLLAMA_API_KEY:
        headers["Authorization"] = (
            "Bearer " + OLLAMA_API_KEY
        )

    tags_url = (
        f"{parsed.scheme}://{parsed.netloc}/api/tags"
    )

    request = urllib.request.Request(
        tags_url,
        headers=headers,
        method="GET"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:
            if response.status >= 400:
                raise RuntimeError(
                    f"Ollama endpoint returned HTTP "
                    f"{response.status}"
                )
    except Exception as error:
        raise RuntimeError(
            "Could not reach Ollama endpoint. "
            "Set DAILY_PROBLEM_OLLAMA_URL and "
            "DAILY_PROBLEM_OLLAMA_API_KEY if needed. "
            f"Details: {error}"
        )

    if not REPO_DIR.exists():
        raise RuntimeError(
            f"Repository does not exist: {REPO_DIR}"
        )

    if not (REPO_DIR / ".git").exists():
        raise RuntimeError(
            f"Not a Git repository: {REPO_DIR}"
        )

    PROBLEMS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


# ============================================================
# GIT STATUS
# ============================================================

def get_git_status():
    result = run_command(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all"
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not read Git status."
        )

    output = result.stdout.strip()

    if not output:
        return []

    return output.splitlines()


# ============================================================
# GIT SYNC
# ============================================================

def git_sync():
    log("Checking Git status...")

    status = get_git_status()

    if status:
        print()
        print("Current Git changes:")

        for item in status:
            print(item)

        raise RuntimeError(
            "Working tree is not clean. "
            "Commit or stash your changes before "
            "running the generator."
        )

    if SKIP_GIT_SYNC:
        log("Skipping git pull (DAILY_PROBLEM_SKIP_GIT_SYNC=1).")
        return

    log("Pulling latest changes...")

    result = run_command(
        [
            "git",
            "pull",
            "--ff-only",
            "origin",
            MAIN_BRANCH
        ],
        timeout=120
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git pull failed."
        )

    log("Git repository is up to date.")


# ============================================================
# EXISTING PROBLEMS
# ============================================================

def get_existing_problems():
    problems = []

    if not PROBLEMS_DIR.exists():
        return problems

    for folder in sorted(PROBLEMS_DIR.iterdir()):
        if not folder.is_dir():
            continue

        if (folder / "problem.md").exists():
            problems.append(folder.name)

    return problems


def build_existing_summary(existing):
    if not existing:
        return "No existing problems."

    recent = existing[-MAX_EXISTING_PROBLEMS:]

    return "\n".join(
        "- " + name.replace("-", " ")
        for name in recent
    )


# ============================================================
# OLLAMA
# ============================================================

def call_ollama(prompt, temperature=0.4):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_ctx": 4096
        }
    }

    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json"
    }

    if OLLAMA_API_KEY:
        headers["Authorization"] = (
            "Bearer " + OLLAMA_API_KEY
        )

    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=OLLAMA_TIMEOUT
        ) as response:
            raw = response.read().decode("utf-8")

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not connect to Ollama: {error}"
        )

    except Exception as error:
        raise RuntimeError(
            f"Ollama request failed: {error}"
        )

    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(
            "Ollama returned invalid JSON."
        )

    response_text = outer.get(
        "response",
        ""
    ).strip()

    if not response_text:
        raise RuntimeError(
            "Ollama returned an empty response."
        )

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    cleaned = response_text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]

    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        raise RuntimeError(
            "Ollama response could not be parsed as JSON."
        )


# ============================================================
# PROBLEM VALIDATION
# ============================================================

def validate_problem_structure(problem):
    required = [
        "title",
        "slug",
        "statement",
        "input",
        "output",
        "constraints",
        "examples",
        "approach",
        "complexity",
        "solution_cpp"
    ]

    for field in required:
        if field not in problem:
            raise RuntimeError(
                f"Generated problem is missing field: {field}"
            )

    if not isinstance(problem["examples"], list):
        raise RuntimeError(
            "Examples must be a list."
        )

    if len(problem["examples"]) < 2:
        raise RuntimeError(
            "At least two examples are required."
        )


# ============================================================
# CPP VALIDATION
# ============================================================

def validate_cpp_source(code):
    if not isinstance(code, str):
        raise RuntimeError(
            "solution_cpp is not a string."
        )

    if not code.strip():
        raise RuntimeError(
            "Generated C++ solution is empty."
        )

    if not re.search(
        r"\bmain\s*\(",
        code
    ):
        raise RuntimeError(
            "Generated C++ solution does not contain "
            "a main() function."
        )

    if re.search(
        r"\bWinMain\s*\(",
        code
    ):
        raise RuntimeError(
            "Generated solution uses WinMain()."
        )


# ============================================================
# GENERATE PROBLEM
# ============================================================

def generate_problem(existing_summary):
    example_structure = {
        "title": "Problem title",
        "slug": "lowercase-hyphen-separated-slug",
        "statement": "Problem statement",
        "input": "Input description",
        "output": "Output description",
        "constraints": "Constraints",
        "examples": [
            {
                "input": "example input",
                "output": "example output"
            },
            {
                "input": "example input",
                "output": "example output"
            }
        ],
        "approach": "Solution explanation",
        "complexity": "Time and space complexity",
        "solution_cpp": (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    return 0;\n"
            "}"
        )
    }

    prompt = "\n".join([
        "Generate exactly ONE new competitive programming problem.",
        "",
        "Existing problems:",
        existing_summary,
        "",
        "Requirements:",
        "- The problem must be new.",
        "- Do not duplicate existing problems.",
        "- Use C++17.",
        "- The solution must be a complete console program.",
        "- The solution MUST contain int main().",
        "- NEVER use WinMain().",
        "- Use standard input and output.",
        "- No GUI.",
        "- No external libraries.",
        "- Compile command:",
        "  g++ -std=c++17 -O2 -Wall -Wextra",
        "- Include at least two sample tests.",
        "",
        "VERY IMPORTANT:",
        "- Check the examples against the solution.",
        "- The expected outputs must actually be correct.",
        "- The solution must produce the exact sample outputs.",
        "",
        "Return ONLY valid JSON.",
        "",
        "Required JSON structure:",
        json.dumps(
            example_structure,
            indent=2
        )
    ])

    log(
        "Asking Ollama to generate a new problem..."
    )

    return call_ollama(
        prompt,
        temperature=0.5
    )


# ============================================================
# FOLDER
# ============================================================

def get_unique_folder(slug):
    slug = str(slug).strip().lower()

    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        slug
    )

    slug = slug.strip("-")

    if not slug:
        slug = "daily-cpp-problem"

    base = slug
    counter = 2

    while (PROBLEMS_DIR / slug).exists():
        slug = f"{base}-{counter}"
        counter += 1

    return slug


# ============================================================
# CREATE FILES
# ============================================================

def create_problem_files(problem, folder_name):
    folder = PROBLEMS_DIR / folder_name

    folder.mkdir(
        parents=True,
        exist_ok=False
    )

    sections = []

    for index, example in enumerate(
        problem["examples"],
        start=1
    ):
        sections.append(
            f"### Example {index}\n\n"
            f"**Input:**\n"
            f"```text\n"
            f"{example.get('input', '')}\n"
            f"```\n\n"
            f"**Output:**\n"
            f"```text\n"
            f"{example.get('output', '')}\n"
            f"```"
        )

    examples_text = "\n\n".join(sections)

    problem_md = (
        f"# {problem['title']}\n\n"
        f"## Problem Statement\n\n"
        f"{problem['statement']}\n\n"
        f"## Input\n\n"
        f"{problem['input']}\n\n"
        f"## Output\n\n"
        f"{problem['output']}\n\n"
        f"## Constraints\n\n"
        f"{problem['constraints']}\n\n"
        f"## Examples\n\n"
        f"{examples_text}\n\n"
        f"## Approach\n\n"
        f"{problem['approach']}\n\n"
        f"## Complexity\n\n"
        f"{problem['complexity']}\n"
    )

    (folder / "problem.md").write_text(
        problem_md,
        encoding="utf-8"
    )

    (folder / "solution.cpp").write_text(
        problem["solution_cpp"],
        encoding="utf-8"
    )

    return folder


# ============================================================
# COMPILE
# ============================================================

def compile_solution(folder):
    source = folder / "solution.cpp"
    executable_name = (
        "solution.exe"
        if os.name == "nt"
        else "solution.out"
    )
    executable = folder / executable_name

    if executable.exists():
        executable.unlink()

    log("Compiling solution...")

    result = subprocess.run(
        [
            GPP,
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            str(source),
            "-o",
            str(executable)
        ],
        cwd=str(folder),
        capture_output=True,
        text=True,
        timeout=TEST_TIMEOUT
    )

    if result.returncode != 0:
        error = (
            "Compilation failed.\n\n"
            + result.stdout
            + "\n"
            + result.stderr
        )

        print(error)

        if executable.exists():
            executable.unlink()

        raise RuntimeError(error)

    log("Compilation successful.")

    return executable


# ============================================================
# OUTPUT NORMALIZATION
# ============================================================

def normalize_output(text):
    return "\n".join(
        line.rstrip()
        for line in text.strip().splitlines()
    ).strip()


# ============================================================
# SAMPLE TEST
# ============================================================

def run_sample_test(
    executable,
    example,
    number
):
    input_data = str(
        example.get("input", "")
    )

    expected = normalize_output(
        str(
            example.get(
                "output",
                ""
            )
        )
    )

    try:
        result = subprocess.run(
            [str(executable)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT
        )

    except subprocess.TimeoutExpired:
        print(
            f"Sample {number}: TIMEOUT"
        )

        return (
            False,
            input_data,
            expected,
            "",
            "Program timed out."
        )

    actual = normalize_output(
        result.stdout
    )

    if result.returncode != 0:
        print(
            f"Sample {number}: RUNTIME ERROR"
        )

        return (
            False,
            input_data,
            expected,
            actual,
            "Runtime error:\n" + result.stderr
        )

    if actual != expected:
        print(
            f"Sample {number}: FAIL"
        )

        return (
            False,
            input_data,
            expected,
            actual,
            (
                "Sample output mismatch."
            )
        )

    print(
        f"Sample {number}: PASS"
    )

    return (
        True,
        input_data,
        expected,
        actual,
        ""
    )


# ============================================================
# TEST SOLUTION
# ============================================================

def test_solution(folder, problem):
    executable = compile_solution(
        folder
    )

    examples = problem["examples"]

    print(
        f"Running {len(examples)} sample test(s)..."
    )

    try:
        for index, example in enumerate(
            examples,
            start=1
        ):
            result = run_sample_test(
                executable,
                example,
                index
            )

            passed = result[0]

            if not passed:
                (
                    _,
                    input_data,
                    expected,
                    actual,
                    reason
                ) = result

                error = (
                    f"{reason}\n\n"
                    f"Failing sample number: {index}\n\n"
                    f"Input:\n"
                    f"{input_data}\n\n"
                    f"Expected output:\n"
                    f"{expected}\n\n"
                    f"Actual output:\n"
                    f"{actual}\n"
                )

                raise RuntimeError(error)

    finally:
        if executable.exists():
            executable.unlink()

    log(
        "All sample tests passed."
    )


# ============================================================
# REPAIR SOLUTION
# ============================================================

def repair_solution(
    problem,
    current_code,
    error_message
):
    examples = json.dumps(
        problem["examples"],
        indent=2
    )

    prompt = "\n".join([
        "You are debugging a C++17 competitive programming solution.",
        "",
        "Problem:",
        problem["title"],
        "",
        "Statement:",
        problem["statement"],
        "",
        "Input:",
        problem["input"],
        "",
        "Output:",
        problem["output"],
        "",
        "Constraints:",
        problem["constraints"],
        "",
        "Examples:",
        examples,
        "",
        "Current solution:",
        current_code,
        "",
        "VALIDATOR ERROR:",
        error_message,
        "",
        "IMPORTANT DEBUGGING INSTRUCTIONS:",
        "1. Identify exactly why the failing sample is wrong.",
        "2. Manually trace the failing input.",
        "3. Compare expected output with actual output.",
        "4. Fix the algorithm, not only formatting.",
        "5. If the current algorithm is wrong, replace it.",
        "6. Make sure every sample passes.",
        "",
        "STRICT REQUIREMENTS:",
        "- Return ONLY JSON.",
        "- JSON must contain solution_cpp.",
        "- solution_cpp must be a complete C++17 program.",
        "- It MUST contain int main().",
        "- NEVER use WinMain().",
        "- Use standard input/output.",
        "- No external libraries.",
        "- Must compile with:",
        "  g++ -std=c++17 -O2 -Wall -Wextra",
        "",
        "Return:",
        json.dumps(
            {
                "solution_cpp": (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "int main() {\n"
                    "    return 0;\n"
                    "}"
                )
            },
            indent=2
        )
    ])

    log(
        "Asking Ollama to repair the solution..."
    )

    repaired = call_ollama(
        prompt,
        temperature=0.2
    )

    if "solution_cpp" not in repaired:
        raise RuntimeError(
            "AI repair did not return solution_cpp."
        )

    code = repaired["solution_cpp"]

    validate_cpp_source(code)

    return code


# ============================================================
# REGENERATE COMPLETELY NEW SOLUTION
# ============================================================

def regenerate_solution(
    problem,
    old_code,
    error_message,
    attempt
):
    examples = json.dumps(
        problem["examples"],
        indent=2
    )

    prompt = "\n".join([
        "Generate a completely NEW C++17 solution.",
        "",
        "IMPORTANT:",
        "Do NOT simply modify the previous code.",
        "Use a different algorithm or implementation approach.",
        "",
        f"Regeneration attempt: {attempt}",
        "",
        "Problem title:",
        problem["title"],
        "",
        "Problem statement:",
        problem["statement"],
        "",
        "Input:",
        problem["input"],
        "",
        "Output:",
        problem["output"],
        "",
        "Constraints:",
        problem["constraints"],
        "",
        "Examples:",
        examples,
        "",
        "Previous incorrect solution:",
        old_code,
        "",
        "Previous validation error:",
        error_message,
        "",
        "Before returning the code:",
        "1. Trace every provided sample manually.",
        "2. Verify expected outputs.",
        "3. Check edge cases.",
        "4. Make sure the algorithm matches the statement.",
        "",
        "STRICT REQUIREMENTS:",
        "- Return ONLY JSON.",
        "- JSON must contain solution_cpp.",
        "- Complete C++17 console program.",
        "- Must contain int main().",
        "- NEVER use WinMain().",
        "- Standard input/output only.",
        "- No external libraries.",
        "- Compile with:",
        "  g++ -std=c++17 -O2 -Wall -Wextra",
        "",
        "Return:",
        json.dumps(
            {
                "solution_cpp": (
                    "#include <iostream>\n"
                    "using namespace std;\n\n"
                    "int main() {\n"
                    "    return 0;\n"
                    "}"
                )
            },
            indent=2
        )
    ])

    log(
        "Asking Ollama to generate a completely "
        "new solution..."
    )

    regenerated = call_ollama(
        prompt,
        temperature=0.45
    )

    if "solution_cpp" not in regenerated:
        raise RuntimeError(
            "AI regeneration did not return solution_cpp."
        )

    code = regenerated["solution_cpp"]

    validate_cpp_source(code)

    return code


# ============================================================
# VALIDATION PIPELINE
# ============================================================

def validate_and_repair_solution(
    folder,
    problem
):
    last_error = ""

    # --------------------------------------------------------
    # Initial validation + repairs
    # --------------------------------------------------------

    for attempt in range(
        1,
        MAX_REPAIR_ATTEMPTS + 1
    ):
        print()
        print("=" * 60)
        print(
            f"Validation attempt "
            f"{attempt}/{MAX_REPAIR_ATTEMPTS}"
        )
        print("=" * 60)

        try:
            validate_problem_structure(
                problem
            )

            validate_cpp_source(
                problem["solution_cpp"]
            )

            test_solution(
                folder,
                problem
            )

            return True

        except RuntimeError as error:
            last_error = str(error)

            print()
            print(last_error)

            if attempt >= MAX_REPAIR_ATTEMPTS:
                break

            print()

            log(
                "Attempting automatic AI repair..."
            )

            try:
                source = (
                    folder / "solution.cpp"
                )

                current_code = (
                    source.read_text(
                        encoding="utf-8"
                    )
                )

                repaired = repair_solution(
                    problem,
                    current_code,
                    last_error
                )

                problem[
                    "solution_cpp"
                ] = repaired

                source.write_text(
                    repaired,
                    encoding="utf-8"
                )

                log(
                    "AI repair applied."
                )

            except Exception as repair_error:
                print(
                    "AI repair failed:"
                )
                print(
                    repair_error
                )

    # --------------------------------------------------------
    # Complete regeneration fallback
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("REPAIR FAILED")
    print("=" * 60)

    print(
        "Trying completely new solution generation..."
    )

    for regen_attempt in range(
        1,
        MAX_REGENERATION_ATTEMPTS + 1
    ):
        print()
        print(
            f"Regeneration attempt "
            f"{regen_attempt}/"
            f"{MAX_REGENERATION_ATTEMPTS}"
        )

        try:
            source = (
                folder / "solution.cpp"
            )

            old_code = (
                source.read_text(
                    encoding="utf-8"
                )
            )

            new_code = regenerate_solution(
                problem,
                old_code,
                last_error,
                regen_attempt
            )

            problem[
                "solution_cpp"
            ] = new_code

            source.write_text(
                new_code,
                encoding="utf-8"
            )

            log(
                "Completely new solution generated."
            )

            # Test the new solution.
            test_solution(
                folder,
                problem
            )

            log(
                "New solution passed all samples."
            )

            return True

        except RuntimeError as error:
            last_error = str(error)

            print()
            print(last_error)

        except Exception as error:
            last_error = str(error)

            print()
            print(
                "Regeneration error:"
            )
            print(error)

    return False


# ============================================================
# GIT SAFETY
# ============================================================

def validate_git_changes(folder):
    status = get_git_status()

    relative_folder = folder.relative_to(
        REPO_DIR
    ).as_posix()

    allowed_prefix = (
        relative_folder + "/"
    )

    unexpected = []

    for item in status:
        path = (
            item[3:]
            if len(item) >= 3
            else item
        )

        if path == relative_folder:
            continue

        if path.startswith(
            allowed_prefix
        ):
            continue

        unexpected.append(item)

    if unexpected:
        print()
        print(
            "Unexpected Git changes:"
        )

        for item in unexpected:
            print(item)

        raise RuntimeError(
            "Unexpected files were modified."
        )

    log(
        "Git safety check passed."
    )


# ============================================================
# GIT ADD
# ============================================================

def stage_generated_problem(folder):
    relative_folder = folder.relative_to(
        REPO_DIR
    ).as_posix()

    log(
        "Staging generated problem only..."
    )

    result = run_command(
        [
            "git",
            "add",
            "--",
            relative_folder
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git add failed."
        )


# ============================================================
# GIT COMMIT
# ============================================================

def commit_generated_problem(title):
    message = (
        f"add daily problem: {title}"
    )

    log(
        "Creating Git commit..."
    )

    result = run_command(
        [
            "git",
            "commit",
            "-m",
            message
        ],
        timeout=120
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git commit failed."
        )


# ============================================================
# GIT PUSH
# ============================================================

def push_changes():
    if SKIP_GIT_PUSH:
        log("Skipping git push (DAILY_PROBLEM_SKIP_GIT_PUSH=1).")
        return

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
        timeout=180
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git push failed."
        )

    log(
        "GitHub push successful."
    )


# ============================================================
# CLEANUP
# ============================================================

def remove_generated_folder(folder):
    if folder is not None and folder.exists():
        log(
            "Removing failed generated problem..."
        )

        shutil.rmtree(
            folder,
            ignore_errors=True
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
        # 1. Environment
        check_environment()

        # 2. Git
        git_sync()

        # 3. Existing problems
        existing = get_existing_problems()

        existing_summary = (
            build_existing_summary(
                existing
            )
        )

        # 4. Generate problem
        problem = generate_problem(
            existing_summary
        )

        # 5. Basic validation
        validate_problem_structure(
            problem
        )

        # 6. Folder
        folder_name = get_unique_folder(
            problem["slug"]
        )

        generated_folder = (
            PROBLEMS_DIR / folder_name
        )

        # 7. Files
        log(
            f"Creating problem: "
            f"{problem['title']}"
        )

        create_problem_files(
            problem,
            folder_name
        )

        # 8. Validate / repair / regenerate
        success = validate_and_repair_solution(
            generated_folder,
            problem
        )

        if not success:
            raise RuntimeError(
                "Solution could not be validated "
                "after repair and regeneration attempts."
            )

        # 9. Safety
        validate_git_changes(
            generated_folder
        )

        # 10. Add
        if SKIP_GIT_COMMIT:
            log(
                "Skipping git add "
                "(DAILY_PROBLEM_SKIP_GIT_COMMIT=1)."
            )
        else:
            stage_generated_problem(
                generated_folder
            )

        # 11. Commit
        if SKIP_GIT_COMMIT:
            log(
                "Skipping git commit "
                "(DAILY_PROBLEM_SKIP_GIT_COMMIT=1)."
            )
        else:
            commit_generated_problem(
                problem["title"]
            )

        # 12. Push
        push_changes()

        # 13. Success
        print()
        print("=" * 60)
        print(
            "                         SUCCESS"
        )
        print("=" * 60)
        print()

        print(
            f"Problem: {problem['title']}"
        )

        print(
            f"Folder: problems/{folder_name}"
        )

        if SKIP_GIT_PUSH:
            print(
                "GitHub push: skipped by config"
            )
        else:
            print(
                "GitHub: pushed successfully"
            )

        print()

        return 0

    except Exception as error:
        print()
        print("=" * 60)
        print(
            "                         FAILED"
        )
        print("=" * 60)
        print()

        print(error)
        print()

        remove_generated_folder(
            generated_folder
        )

        return 1


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    sys.exit(main())