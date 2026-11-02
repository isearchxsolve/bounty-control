"""Cline lifecycle repair with immutable-source and native-receipt guards."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid


# F3/F4: the typed delivery failures are RuntimeError subclasses, so the blanket
# ``except ValueError`` below never caught them and one could escape this boundary as an
# unhandled exception -- which the host then stamped as an engineer failure. They are matched
# by class name so this module stays dependency-free (it is bundled for Kaggle as source).
CLASSIFIED_DELIVERY_FAILURES = ('ClineDeliverableMissing', 'ClineDeliverableInvalid',
                                'InfrastructureFault', 'RunnerShutdown', 'PreparationRace')


def source_snapshot(worktree):
    def git(*args):
        return subprocess.run(['git', '-C', str(worktree), *args], check=True,
                              capture_output=True, timeout=30).stdout
    head = git('rev-parse', 'HEAD')
    diff = git('diff', '--binary', 'HEAD')
    untracked = git('ls-files', '--others', '--exclude-standard', '-z')
    records = []
    root = Path(worktree).resolve()
    for name in untracked.split(b'\0'):
        if not name:
            continue
        relative = name.decode('utf-8', errors='surrogateescape')
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Unsafe preparation artifact in repository: ' + relative)
        records.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(head + diff + json.dumps(records).encode()).hexdigest()


def validate_plan(document, worktree, previous=None):
    if not isinstance(document, dict):
        raise ValueError('Cline decision must be a JSON object')
    if document.get('action') != 'retry':
        raise ValueError(document.get('reason') or 'Cline reported an unresolved prerequisite')
    root = Path(worktree).resolve()
    sources = document.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('A native plan requires repository source citations')
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('Invalid repository source citation')
        path = (root / source.get('path', '')).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Native plan source is outside the repository or missing')
        if hashlib.sha256(path.read_bytes()).hexdigest() != source.get('sha256'):
            raise ValueError('Native plan source SHA-256 does not match the checkout')
    fields = ('bootstrap', 'baseline_tests', 'targeted_tests', 'final_tests', 'linters', 'format_checks', 'builds')
    result = {}
    for field in fields:
        commands = document.get('plan', {}).get(field, [])
        if not isinstance(commands, list) or len(commands) > 32:
            raise ValueError('Invalid native command list: ' + field)
        for command in commands:
            if (not isinstance(command, list) or not command or len(command) > 100
                    or any(not isinstance(arg, str) or '\0' in arg for arg in command)):
                raise ValueError('Native commands must be nonempty argv arrays')
        result[field] = commands
    if not result['baseline_tests'] or not result['final_tests']:
        raise ValueError('Both untouched baseline and final tests are mandatory')
    existing = [tuple(c) for c in (getattr(previous, 'baseline_tests', []) + getattr(previous, 'final_tests', []))]
    for command in result['baseline_tests'] + result['final_tests']:
        if tuple(command) in existing:
            continue
        # Tool selection belongs to Cline. Reject synthetic success commands,
        # not unfamiliar ecosystems, package managers, or native test runners.
        executable = Path(command[0]).name.lower().removesuffix('.exe')
        joined = ' '.join(command)
        if (executable in ('echo', 'true', 'printf')
                or '--passWithNoTests' in command or '--if-present' in command
                or re.search(r'\|\|\s*(?:true|exit\s+0)\b', joined)
                or (executable.startswith('python') and '-c' in command)):
            raise ValueError('Synthetic or bypassed verification command: ' + repr(command))
    if previous:
        def targets(commands):
            return {arg for command in commands for arg in command if arg in ('test', 'pytest', 'unittest', 'check', 'verify') or arg.startswith('test:')}
        if not targets(previous.baseline_tests).issubset(targets(result['baseline_tests'])):
            raise ValueError('Preparation repair dropped an existing baseline test target')
        if previous.linters and not result['linters']:
            raise ValueError('Preparation repair dropped the required linter commands')
    return result


def write_json_atomic(path: Path, document) -> None:
    """Write the control artifact whole, or not at all: no half-readable receipt.

    A reader that catches a truncated file reports an unparseable receipt, which is a
    different fault from a missing one and deserves its own name.
    """
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(document, indent=2), encoding='utf-8')
    temporary.replace(path)


def supervise(worktree, repo, number, phase, failure, plan, artifact_dir,
               command_builder, execute, plan_factory, preserve):
    """Run a bounded repair turn; model conclusions never count as test receipts."""
    folder = Path(artifact_dir).resolve() / 'delivery-supervisor'
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / (uuid.uuid4().hex + '.json')
    journal = receipt.with_suffix('.journal.json')
    failure_file = receipt.with_suffix('.failure.txt')
    failure_file.write_text(str(failure), encoding='utf-8')
    # F5: a write-early skeleton at the receipt's own path, before the command is built, so an
    # aborted turn explains itself instead of vanishing. Measured 2026-11-01
    # (Spectral-Finance/lux#74, run 41357309340): Cline's repair turn was aborted by the
    # supervisor timeout while a background compile still ran, no decision was ever written,
    # and the reader below raised FileNotFoundError -- which the host stamped as
    # BLOCKED_BASELINE, a transient timeout read as a permanent statement about the repository.
    # The skeleton is replaced by Cline's own write; if it survives, the turn did not finish.
    write_json_atomic(receipt, {
        'action': 'incomplete',
        'reason': 'repair turn did not write a decision; it was aborted, killed or timed out',
        'phase': phase, 'repo': repo, 'issue_number': number,
        'started_at': datetime.now(timezone.utc).isoformat(),
    })
    before = source_snapshot(worktree)
    current = {name: getattr(plan, name, []) for name in
               ('bootstrap', 'baseline_tests', 'targeted_tests', 'final_tests', 'linters', 'format_checks', 'builds')}
    plan_file = receipt.with_suffix('.plan.json')
    plan_file.write_text(json.dumps(current, indent=2), encoding='utf-8')
    prompt = f'''You supervise the complete delivery lifecycle of {repo}#{number}.
Current phase: {phase}. Diagnose the actual failure and repair its environment prerequisites.
Read the complete actual failure receipt at {failure_file}; do not truncate it.
Read the complete current native plan at {plan_file}.

Read AGENTS.md, manifests, lockfiles, CI workflows and repository setup documentation.
Resolve declared tools, exact package-manager/JVM versions, native dependencies, and configuration dynamically.
You may install tools and dependencies, configure runtime caches outside the checkout, and run native verification.
The checkout stays the customer's ground in this turn too, for the same reason it did in preparation:
the host proves the delivery by watching one command go from failing to passing against a base that
never moved. You may read, run, install, and measure -- you leave no edit, no new file, no staged
change, and no commit behind, and the host compares the tree byte for byte before it accepts your
artifact. Manufacturing a green baseline by editing that tree erases the evidence the delivery
exists to produce: a failing test is never repaired by changing the source, the suite, or CI.
A failure is not automatically a blocker either. When the failure IS the defect this issue
reports, it is the evidence the delivery exists to produce: put the green subset in
baseline_tests and name the red target in the plan's targeted command as the reproduction,
exactly as the preparation directive says. BLOCKED_BASELINE is for what no amount of engineering
can supply in this environment -- a missing toolchain, a credential, a service, or hardware.
Never bypass a build approval policy, test, linter, funding/competition check, claim lease, or release guard.
Do not send messages, push branches, or create a PR yourself. The host performs guarded publication.
Preserve completed engineering edits and report an external credential/service/hardware blocker honestly.

Write your machine-readable decision to exactly this control artifact outside the checkout: {receipt}
Format: {{"action":"retry" or "blocked","reason":"evidence-backed diagnosis",
"sources":[{{"path":"repository-relative manifest or CI file","sha256":"actual file SHA-256"}}],
"plan":{{"bootstrap":[["program","arg"]],"baseline_tests":[["native","test"]],
"final_tests":[["native","test"]],"builds":[["native","build"]],"linters":[],"format_checks":[]}}}}
For preparation/baseline phases preserve every required native test/lint target and use only real repository commands.
For publication/receipt phases keep the current plan unchanged and repair only transport/tool configuration.
The host will independently validate source integrity, execute the plan, and require successful native receipts.
Finish after saving the artifact; do not claim delivery or test success from inference.'''
    result = execute(command_builder(worktree, prompt), cwd=worktree, timeout=3600)
    evidence = {'repo': repo, 'issue_number': number, 'phase': phase,
                'failure_file': str(failure_file), 'exit_code': result.exit_code,
                'source_before': before}
    try:
        after = source_snapshot(worktree)
        evidence['source_after'] = after
        if after != before:
            evidence['preserved_edits'] = preserve(worktree)
            raise ValueError('Cline changed repository source or HEAD during preparation/publication repair')
        if result.exit_code != 0:
            raise ValueError('Cline delivery repair failed: ' + str(result.stderr or result.stdout)[-1000:])
        document = json.loads(receipt.read_text(encoding='utf-8'))
        if document.get('action') == 'incomplete':
            # The skeleton survived: the turn ended without a decision. That is a timeout or
            # an abort, never a verdict about the repository, and it is named as one.
            raise ValueError('Repair turn finished without a decision: '
                             + str(document.get('reason') or 'no decision was written'))
        evidence['decision'] = document
        if phase in ('preparation', 'baseline'):
            validated = validate_plan(document, worktree, plan)
            recovered = plan_factory(**validated)
        else:
            if document.get('action') != 'retry':
                raise ValueError(document.get('reason') or 'Delivery repair remains blocked')
            recovered = plan
        evidence['status'] = 'REPAIR_READY_FOR_HOST_VERIFICATION'
        return True, recovered, str(journal)
    except (ValueError, OSError, TypeError) as exc:
        evidence['status'] = 'REPAIR_BLOCKED'
        evidence['diagnostic'] = str(exc)
        return False, plan, str(exc)
    except RuntimeError as exc:
        # A typed delivery failure is a diagnosis, not an engineering verdict: classify it
        # and keep the journal and artifacts rather than letting it escape unhandled.
        if type(exc).__name__ not in CLASSIFIED_DELIVERY_FAILURES:
            raise
        evidence['status'] = 'REPAIR_BLOCKED'
        evidence['classification'] = type(exc).__name__
        evidence['diagnostic'] = str(exc)
        return False, plan, str(exc)
    finally:
        journal.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
