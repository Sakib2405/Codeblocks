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

TEST_TIMEOUT = 10
OLLAMA_TIMEOUT = 180

MAX_EXISTING_PROBLEMS = 30
MAX_REPAIR_ATTEMPTS = 3


# ============================================================
# LOGGING
# ============================================================

def log(message):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")


# ============================================================
# COMMAND RUNNER
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
# ENVIRONMENT CHECK
# ============================================================

def check_environment():
    log("Checking environment...")

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Python: {sys.version.split()[0]}"
    )

    # Check g++
    result = run_command([GPP, "--version"])

    if result.returncode != 0:
        raise RuntimeError(
            "g++ was not found."
        )

    compiler_lines = result.stdout.splitlines()

    if compiler_lines:
        log(f"Compiler: {compiler_lines[0]}")

    # Check Ollama
    result = run_command(
        ["ollama", "--version"]
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Ollama was not found."
        )

    ollama_lines = result.stdout.splitlines()

    if ollama_lines:
        log(f"Ollama: {ollama_lines[0]}")

    # Check repository
    if not REPO_DIR.exists():
        raise RuntimeError(
            f"Repository directory does not exist: {REPO_DIR}"
        )

    if not (REPO_DIR / ".git").exists():
        raise RuntimeError(
            f"Not a Git repository: {REPO_DIR}"
        )

    # Create problems folder if necessary
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
            "Commit or stash your changes before running "
            "the generator."
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

        problem_file = folder / "problem.md"

        if problem_file.exists():
            problems.append(folder.name)

    return problems


def build_existing_summary(existing):
    if not existing:
        return "No existing problems."

    recent = existing[-MAX_EXISTING_PROBLEMS:]

    lines = []

    for name in recent:
        readable = name.replace("-", " ")
        lines.append("- " + readable)

    return "\n".join(lines)


# ============================================================
# OLLAMA REQUEST
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

    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
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

    # First try direct JSON
    try:
        return json.loads(response_text)

    except json.JSONDecodeError:
        pass

    # Try removing markdown fences
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
# BASIC PROBLEM VALIDATION
# ============================================================

def validate_problem_structure(problem):
    required_fields = [
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

    for field in required_fields:
        if field not in problem:
            raise RuntimeError(
                f"Generated problem is missing field: {field}"
            )

    if not isinstance(problem["examples"], list):
        raise RuntimeError(
            "Examples must be a list."
        )

    if len(problem["examples"]) == 0:
        raise RuntimeError(
            "Problem has no examples."
        )


# ============================================================
# C++ SOURCE VALIDATION
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

    # Normal main()
    has_main = re.search(
        r"\bmain\s*\(",
        code
    )

    if not has_main:
        raise RuntimeError(
            "Generated C++ solution does not contain a main() function."
        )

    # Windows GUI entry point is not allowed.
    if re.search(
        r"\bWinMain\s*\(",
        code
    ):
        raise RuntimeError(
            "Generated solution uses WinMain(). "
            "A normal console main() function is required."
        )


# ============================================================
# GENERATE NEW PROBLEM
# ============================================================

def generate_problem(existing_summary):
    prompt_parts = [
        "You are generating exactly ONE C++17 competitive "
        "programming problem.",

        "",
        "Existing problems:",
        existing_summary,

        "",
        "IMPORTANT REQUIREMENTS:",

        "1. Generate exactly one NEW problem.",
        "2. Do not duplicate an existing problem.",
        "3. The solution must be a normal console C++17 program.",
        "4. The solution MUST contain int main().",
        "5. NEVER use WinMain().",
        "6. Use standard input and standard output.",
        "7. Do not use GUI APIs.",
        "8. Do not use external libraries.",
        "9. The program must compile with:",
        "   g++ -std=c++17 -O2 -Wall -Wextra",
        "10. Include at least two sample tests.",

        "",
        "The generated problem must contain:",
        "- title",
        "- slug",
        "- statement",
        "- input",
        "- output",
        "- constraints",
        "- examples",
        "- approach",
        "- complexity",
        "- solution_cpp",

        "",
        "Return ONLY valid JSON.",

        "",
        "Use exactly this JSON structure:",

        json.dumps(
            {
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
            },
            indent=2
        ),

        "",
        "IMPORTANT: solution_cpp MUST contain a real int main() "
        "function and must be a complete compilable C++ program."
    ]

    prompt = "\n".join(prompt_parts)

    log(
        "Asking Ollama to generate a new problem..."
    )

    return call_ollama(
        prompt,
        temperature=0.5
    )


# ============================================================
# UNIQUE FOLDER
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
# CREATE PROBLEM FILES
# ============================================================

def create_problem_files(problem, folder_name):
    folder = PROBLEMS_DIR / folder_name

    folder.mkdir(
        parents=True,
        exist_ok=False
    )

    example_sections = []

    for index, example in enumerate(
        problem["examples"],
        start=1
    ):
        example_input = example.get(
            "input",
            ""
        )

        example_output = example.get(
            "output",
            ""
        )

        section = (
            f"### Example {index}\n\n"
            f"**Input:**\n"
            f"```text\n"
            f"{example_input}\n"
            f"```\n\n"
            f"**Output:**\n"
            f"```text\n"
            f"{example_output}\n"
            f"```"
        )

        example_sections.append(section)

    examples_text = "\n\n".join(
        example_sections
    )

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
# COMPILE C++
# ============================================================

def compile_solution(folder):
    source = folder / "solution.cpp"
    executable = folder / "solution.exe"

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
        error_text = (
            "Compilation failed.\n\n"
            + result.stdout
            + "\n"
            + result.stderr
        )

        print(error_text)

        if executable.exists():
            executable.unlink()

        raise RuntimeError(error_text)

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
# RUN ONE SAMPLE
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
            "Program exited with a non-zero "
            "status.\n\n"
            + result.stderr
        )

    if actual != expected:
        print(
            f"Sample {number}: FAIL"
        )

        error = (
            "Sample output mismatch.\n\n"
            f"Expected:\n{expected}\n\n"
            f"Actual:\n{actual}\n"
        )

        return False, error

    print(
        f"Sample {number}: PASS"
    )

    return True, ""


# ============================================================
# TEST SOLUTION
# ============================================================

def test_solution(folder, problem):
    executable = compile_solution(
        folder
    )

    examples = problem.get(
        "examples",
        []
    )

    if not examples:
        raise RuntimeError(
            "Problem has no sample tests."
        )

    print(
        f"Running {len(examples)} sample test(s)..."
    )

    try:
        for index, example in enumerate(
            examples,
            start=1
        ):
            passed, error = run_sample_test(
                executable,
                example,
                index
            )

            if not passed:
                raise RuntimeError(error)

    finally:
        if executable.exists():
            executable.unlink()

    log(
        "All sample tests passed."
    )


# ============================================================
# AI REPAIR
# ============================================================

def repair_solution(
    problem,
    current_code,
    error_message
):
    examples_json = json.dumps(
        problem["examples"],
        indent=2
    )

    prompt_parts = [
        "You are repairing a C++17 competitive "
        "programming solution.",

        "",
        "Problem title:",
        str(problem["title"]),

        "",
        "Problem statement:",
        str(problem["statement"]),

        "",
        "Input:",
        str(problem["input"]),

        "",
        "Output:",
        str(problem["output"]),

        "",
        "Constraints:",
        str(problem["constraints"]),

        "",
        "Examples:",
        examples_json,

        "",
        "Current C++ code:",
        current_code,

        "",
        "Validator error:",
        error_message,

        "",
        "FIX THE SOLUTION.",

        "",
        "STRICT REQUIREMENTS:",
        "1. Return ONLY valid JSON.",
        "2. JSON must contain exactly one field: solution_cpp.",
        "3. solution_cpp must be a complete C++17 program.",
        "4. It MUST contain int main().",
        "5. NEVER use WinMain().",
        "6. It must be a normal console program.",
        "7. Use standard input/output.",
        "8. Do not use external libraries.",
        "9. It must compile with:",
        "   g++ -std=c++17 -O2 -Wall -Wextra",
        "10. It must produce the expected output for "
        "all provided examples.",

        "",
        "Return this JSON structure:",
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
    ]

    prompt = "\n".join(
        prompt_parts
    )

    log(
        "Asking Ollama to repair the solution..."
    )

    repaired = call_ollama(
        prompt,
        temperature=0.2
    )

    if "solution_cpp" not in repaired:
        raise RuntimeError(
            "AI repair response did not contain "
            "solution_cpp."
        )

    repaired_code = repaired[
        "solution_cpp"
    ]

    validate_cpp_source(
        repaired_code
    )

    return repaired_code


# ============================================================
# VALIDATE + REPAIR LOOP
# ============================================================

def validate_and_repair_solution(
    folder,
    problem
):
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
            # Validate generated source.
            validate_problem_structure(
                problem
            )

            validate_cpp_source(
                problem["solution_cpp"]
            )

            # Compile + sample tests.
            test_solution(
                folder,
                problem
            )

            return True

        except RuntimeError as error:
            error_message = str(error)

            print()
            print(error_message)

            # No more repair attempts.
            if attempt >= MAX_REPAIR_ATTEMPTS:
                return False

            print()
            log(
                "Attempting automatic AI repair..."
            )

            try:
                source_file = (
                    folder / "solution.cpp"
                )

                current_code = (
                    source_file.read_text(
                        encoding="utf-8"
                    )
                )

                repaired_code = repair_solution(
                    problem,
                    current_code,
                    error_message
                )

                # Update in-memory problem.
                problem[
                    "solution_cpp"
                ] = repaired_code

                # Save repaired solution.
                source_file.write_text(
                    repaired_code,
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

                if attempt >= MAX_REPAIR_ATTEMPTS:
                    return False

    return False


# ============================================================
# GIT SAFETY CHECK
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
        if len(item) >= 3:
            path = item[3:]
        else:
            path = item

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

def commit_generated_problem(
    title
):
    commit_message = (
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
            commit_message
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

def remove_generated_folder(
    folder
):
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
        # ----------------------------------------------------
        # 1. Environment
        # ----------------------------------------------------

        check_environment()

        # ----------------------------------------------------
        # 2. Git sync
        # ----------------------------------------------------

        git_sync()

        # ----------------------------------------------------
        # 3. Existing problems
        # ----------------------------------------------------

        existing = get_existing_problems()

        existing_summary = (
            build_existing_summary(
                existing
            )
        )

        # ----------------------------------------------------
        # 4. Generate problem
        # ----------------------------------------------------

        problem = generate_problem(
            existing_summary
        )

        # ----------------------------------------------------
        # 5. Basic structure
        # ----------------------------------------------------

        validate_problem_structure(
            problem
        )

        # ----------------------------------------------------
        # 6. Unique folder
        # ----------------------------------------------------

        folder_name = get_unique_folder(
            problem["slug"]
        )

        generated_folder = (
            PROBLEMS_DIR / folder_name
        )

        # ----------------------------------------------------
        # 7. Create files
        # ----------------------------------------------------

        log(
            f"Creating problem: "
            f"{problem['title']}"
        )

        create_problem_files(
            problem,
            folder_name
        )

        # ----------------------------------------------------
        # 8. Compile + test + repair
        # ----------------------------------------------------

        success = (
            validate_and_repair_solution(
                generated_folder,
                problem
            )
        )

        if not success:
            raise RuntimeError(
                "Solution could not be validated "
                "after automatic repair attempts."
            )

        # ----------------------------------------------------
        # 9. Git safety
        # ----------------------------------------------------

        validate_git_changes(
            generated_folder
        )

        # ----------------------------------------------------
        # 10. Git add
        # ----------------------------------------------------

        stage_generated_problem(
            generated_folder
        )

        # ----------------------------------------------------
        # 11. Git commit
        # ----------------------------------------------------

        commit_generated_problem(
            problem["title"]
        )

        # ----------------------------------------------------
        # 12. Git push
        # ----------------------------------------------------

        push_changes()

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

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

        # Remove generated problem if anything failed.
        remove_generated_folder(
            generated_folder
        )

        return 1


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    sys.exit(main())