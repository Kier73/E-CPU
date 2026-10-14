"""Native command-line entry point for the MailCPU virtual environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .environment import VirtualEnvironment
from .headless import HeadlessOS
from .image import ExecutableImage, ImageFile
from .model import DEFAULT_MAX_TICKS, Instruction, Op, Program
from .trajectory import TrajectoryWriter
from .vm import MailCPUVirtualMachine
from .registry import ImageRegistry
from .owned_network import NetworkAddress


_HEADLESS_DEMO_SOURCE = """\
set n 3
set one 1
set zero 0
set minus_one -1
loop:
compare positive n zero
branch positive decrement
halt
decrement:
add n n minus_one
branch one loop
"""

_COMMANDS = (
    "boot",
    "make-image",
    "run-image",
    "demo",
    "run-source",
    "restore-run",
    "os-demo",
    "memory-demo",
    "network-demo",
    "registry-publish",
    "registry-list",
)


def demo_image() -> ExecutableImage:
    """Mathematics: construct a finite executable image whose result register satisfies `result = 20 + 22 = 42`."""

    program = Program(
        (
            Instruction(Op.SET, ("left", 20)),
            Instruction(Op.SET, ("right", 22)),
            Instruction(Op.ADD, ("result", "left", "right")),
            Instruction(Op.HALT),
        )
    )
    return ExecutableImage(
        "hello-mailcpu",
        program,
        (
            ImageFile("/opt/mailcpu/README", b"This file arrived inside a MailCPU image.\n"),
        ),
        (("MAILCPU_MODE", "native"),),
    )


def _command_boot(_: argparse.Namespace) -> int:
    """Mathematics: expose the boot image projection `list(/) = sorted(dom(root.children))`."""

    environment = VirtualEnvironment.bootstrap()
    print("\n".join(environment.kernel.fs.listdir("/")))
    return 0


def _command_make_image(arguments: argparse.Namespace) -> int:
    """Mathematics: persist `demo_image()` and report its content identity `SHA256(image)`."""

    image = demo_image()
    image.save(arguments.path)
    print(json.dumps({"path": str(arguments.path), "digest": image.digest()}, sort_keys=True))
    return 0


def _command_run_image(arguments: argparse.Namespace) -> int:
    """Mathematics: execute image orbit `s_k = T^k(s_0)` for at most `max_ticks` scheduler ticks."""

    image = ExecutableImage.load(arguments.path)
    image.require_supported()
    environment = VirtualEnvironment.bootstrap()
    image.install(environment)
    trajectory_paths: dict[str, str] = {}
    if arguments.trajectory_dir:
        trajectory_dir = Path(arguments.trajectory_dir)
        trajectory_dir.mkdir(parents=True, exist_ok=True)
        data_path = trajectory_dir / f"{image.name}.mtrj"
        index_path = trajectory_dir / f"{image.name}.mtrj.idx"
        with TrajectoryWriter(data_path, index_path) as writer:
            vm = MailCPUVirtualMachine(environment, trajectory=writer)
            pid = vm.spawn_program(image.program, image.name)
            events = vm.run(arguments.max_ticks)
        trajectory_paths = {"data": str(data_path), "index": str(index_path)}
    else:
        vm = MailCPUVirtualMachine(environment)
        pid = vm.spawn_program(image.program, image.name)
        events = vm.run(arguments.max_ticks)
    task = vm.scheduler.tasks[pid]
    print(
        json.dumps(
            {
                "image": image.name,
                "digest": image.digest(),
                "pid": pid,
                "ticks": len(events),
                "status": task.status.value,
                "registers": task.backend.snapshot_registers(),
                "installed_files": [item.path for item in image.files],
                "trajectory": trajectory_paths,
            },
            sort_keys=True,
        )
    )
    return 0 if task.status.value == "halted" else 1


def _command_demo(_: argparse.Namespace) -> int:
    """Mathematics: run the complete native path `image -> install -> schedule -> result` and print its projection."""

    image = demo_image()
    environment = VirtualEnvironment.bootstrap()
    image.install(environment)
    vm = MailCPUVirtualMachine(environment)
    pid = vm.spawn_program(image.program, image.name)
    vm.run()
    task = vm.scheduler.tasks[pid]
    print(
        json.dumps(
            {
                "root": environment.kernel.fs.listdir("/"),
                "image": image.name,
                "result": task.backend.registers.get("result"),
                "status": task.status.value,
            },
            sort_keys=True,
        )
    )
    return 0


def _command_run_source(arguments: argparse.Namespace) -> int:
    """Mathematics: map host source through `UTF8 -> virtual file -> assemble -> schedule` and report the process projection."""

    source_path = Path(arguments.path)
    source = source_path.read_text(encoding="utf-8")
    virtual_path = f"/run/{source_path.name}"
    trajectory_paths: dict[str, str] = {}
    if arguments.trajectory_dir:
        trajectory_dir = Path(arguments.trajectory_dir)
        trajectory_dir.mkdir(parents=True, exist_ok=True)
        data_path = trajectory_dir / f"{source_path.stem}.mtrj"
        index_path = trajectory_dir / f"{source_path.stem}.mtrj.idx"
        with TrajectoryWriter(data_path, index_path) as writer:
            operating_system = HeadlessOS(trajectory=writer)
            operating_system.install_source(virtual_path, source)
            report = operating_system.run_file(
                virtual_path,
                max_ticks=arguments.max_ticks,
                name=source_path.stem,
                max_pages=arguments.max_pages,
            )
        trajectory_paths = {"data": str(data_path), "index": str(index_path)}
    else:
        operating_system = HeadlessOS()
        operating_system.install_source(virtual_path, source)
        report = operating_system.run_file(
            virtual_path,
            max_ticks=arguments.max_ticks,
            name=source_path.stem,
            max_pages=arguments.max_pages,
        )
    checkpoint_payload: dict[str, str] = {}
    if arguments.checkpoint_out:
        checkpoint_payload = {
            "path": str(arguments.checkpoint_out),
            "digest": operating_system.save_checkpoint(arguments.checkpoint_out),
        }
    print(
        json.dumps(
            {
                "source": str(source_path),
                "virtual_path": virtual_path,
                "process": report.to_dict(),
                "trajectory": trajectory_paths,
                "checkpoint": checkpoint_payload,
            },
            sort_keys=True,
        )
    )
    return 0 if report.status == "exited" else 1


def _command_restore_run(arguments: argparse.Namespace) -> int:
    """Mathematics: continue checkpoint orbit `S_{k+1} = T(S_k)` and report every restored process projection."""

    operating_system = HeadlessOS.restore_checkpoint(arguments.path)
    events = operating_system.run(arguments.max_ticks)
    reports = [report.to_dict() for report in operating_system.processes()]
    print(
        json.dumps(
            {
                "checkpoint": str(arguments.path),
                "ticks": len(events),
                "processes": reports,
            },
            sort_keys=True,
        )
    )
    user_reports = [report for report in operating_system.processes() if report.pid != operating_system.environment.init_pid]
    return 0 if user_reports and all(report.status == "exited" for report in user_reports) else 1


def _command_os_demo(_: argparse.Namespace) -> int:
    """Mathematics: exercise the path `source -> virtual inode -> process -> EXITED` with a countdown workload and report the process table."""

    operating_system = HeadlessOS()
    virtual_path = operating_system.install_source("/home/countdown.mca", _HEADLESS_DEMO_SOURCE)
    report = operating_system.run_file(virtual_path, name="countdown")
    print(json.dumps({"virtual_path": virtual_path, "process": report.to_dict()}, sort_keys=True))
    return 0 if report.status == "exited" else 1


def _command_memory_demo(_: argparse.Namespace) -> int:
    """Mathematics: exercise the identity `M_writer[x] = M_reader[x]` across a checkpoint projection and report both observations."""

    operating_system = HeadlessOS()
    writer = operating_system.launch_source("halt\n", "memory-writer", max_pages=3)
    reader = operating_system.launch_source("halt\n", "memory-reader", max_pages=3)
    operating_system.syscall(writer, "shm_create", name="mailbox", size=4096)
    operating_system.syscall(writer, "shm_attach", name="mailbox", start=8192)
    operating_system.syscall(reader, "shm_attach", name="mailbox", start=8192, writable=False)
    operating_system.syscall(writer, "mem_write", address=8192, data=b"mailcpu-memory")
    before = operating_system.syscall(reader, "mem_read", address=8192, size=14)
    restored = HeadlessOS.from_snapshot(operating_system.snapshot())
    after = restored.syscall(reader, "mem_read", address=8192, size=14)
    result = {
        "shared_before_checkpoint": before.decode("ascii"),
        "shared_after_checkpoint": after.decode("ascii"),
        "journal_valid": restored.environment.kernel.journal.verify(),
        "region_names": sorted(restored.vm.shared_regions),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if before == after and result["journal_valid"] else 1


def _command_network_demo(_: argparse.Namespace) -> int:
    """Mathematics: exercise `bind -> routed_send -> demux_receive` and report the datagram payload and route evidence."""

    operating_system = HeadlessOS()
    pid = operating_system.environment.init_pid
    for namespace in ("bridge", "omega"):
        operating_system.syscall(pid, "net_namespace_create", name=namespace)
    operating_system.syscall(pid, "net_interface_create", namespace="root", interface="eth0")
    operating_system.syscall(pid, "net_interface_create", namespace="bridge", interface="eth0")
    operating_system.syscall(pid, "net_interface_create", namespace="bridge", interface="eth1")
    operating_system.syscall(pid, "net_interface_create", namespace="omega", interface="eth0")
    operating_system.syscall(
        pid,
        "net_connect",
        link="root-bridge",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="bridge",
        right_interface="eth0",
    )
    operating_system.syscall(
        pid,
        "net_connect",
        link="bridge-omega",
        left_namespace="bridge",
        left_interface="eth1",
        right_namespace="omega",
        right_interface="eth0",
    )
    source_socket = operating_system.syscall(
        pid,
        "net_dgram_bind",
        namespace="root",
        interface="eth0",
        port=6000,
    )
    destination_socket = operating_system.syscall(
        pid,
        "net_dgram_bind",
        namespace="omega",
        interface="eth0",
        port=7000,
    )
    operating_system.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="omega",
        destination_interface="eth0",
        destination_port=7000,
        payload=b"mailcpu-datagram",
        logical_time=1,
    )
    datagram = operating_system.syscall(pid, "net_dgram_receive", socket_id=destination_socket)
    if datagram is None:
        return 1
    print(
        json.dumps(
            {
                "payload": datagram.payload.decode("ascii"),
                "route": [address.path() for address in datagram.route],
                "journal_valid": operating_system.environment.kernel.journal.verify(),
                "source": NetworkAddress("root", "eth0").path(),
            },
            sort_keys=True,
        )
    )
    return 0 if datagram.payload == b"mailcpu-datagram" and operating_system.environment.kernel.journal.verify() else 1


def _command_registry_publish(arguments: argparse.Namespace) -> int:
    """Mathematics: publish image identity `h = SHA256(load(path))` into digest-addressed registry `R[h]`."""

    image = ExecutableImage.load(arguments.image)
    record = ImageRegistry(arguments.root).publish(image)
    print(json.dumps({"digest": record.digest, "name": record.name, "path": record.path}, sort_keys=True))
    return 0


def _command_registry_list(arguments: argparse.Namespace) -> int:
    """Mathematics: enumerate validated finite registry domain `sort(dom(R))` as JSON records."""

    records = ImageRegistry(arguments.root).list()
    print(json.dumps([record.__dict__ for record in records], sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Mathematics: construct the command grammar `G` such that `dom(G)` equals `_COMMANDS` exactly."""

    parser = argparse.ArgumentParser(prog="mailcpu", description="Native MailCPU virtual environment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    boot = subparsers.add_parser("boot", help="show the native boot namespace")
    boot.set_defaults(handler=_command_boot)
    make_image = subparsers.add_parser("make-image", help="write the deterministic demo image")
    make_image.add_argument("path")
    make_image.set_defaults(handler=_command_make_image)
    run_image = subparsers.add_parser("run-image", help="run a MailCPU executable image")
    run_image.add_argument("path")
    run_image.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    run_image.add_argument("--trajectory-dir", help="write an indexed receipt-verified trajectory")
    run_image.set_defaults(handler=_command_run_image)
    demo = subparsers.add_parser("demo", help="boot, install, schedule, and report the demo image")
    demo.set_defaults(handler=_command_demo)
    run_source = subparsers.add_parser("run-source", help="run an assembly source file inside the headless OS")
    run_source.add_argument("path")
    run_source.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    run_source.add_argument("--max-pages", type=int, help="per-process virtual memory page quota")
    run_source.add_argument("--trajectory-dir", help="write an indexed receipt-verified trajectory")
    run_source.add_argument("--checkpoint-out", help="save a continuation-capable checkpoint after execution")
    run_source.set_defaults(handler=_command_run_source)
    restore_run = subparsers.add_parser("restore-run", help="restore a checkpoint and continue its virtual processes")
    restore_run.add_argument("path")
    restore_run.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    restore_run.set_defaults(handler=_command_restore_run)
    os_demo = subparsers.add_parser("os-demo", help="run source stored in the virtual filesystem")
    os_demo.set_defaults(handler=_command_os_demo)
    memory_demo = subparsers.add_parser("memory-demo", help="exercise private and shared memory through the native ABI")
    memory_demo.set_defaults(handler=_command_memory_demo)
    network_demo = subparsers.add_parser("network-demo", help="exercise routed owned datagrams through the native ABI")
    network_demo.set_defaults(handler=_command_network_demo)
    registry_publish = subparsers.add_parser("registry-publish", help="publish an image into a digest-addressed registry")
    registry_publish.add_argument("root")
    registry_publish.add_argument("image")
    registry_publish.set_defaults(handler=_command_registry_publish)
    registry_list = subparsers.add_parser("registry-list", help="list validated images in a local registry")
    registry_list.add_argument("root")
    registry_list.set_defaults(handler=_command_registry_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Mathematics: parse argv under grammar `G` and evaluate exactly one command handler."""

    parser = build_parser()
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)
