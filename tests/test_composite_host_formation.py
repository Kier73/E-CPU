"""SAB-011: formation-driven execution, independent relay/storage and recovery."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from mailcpu.adaptive_placement import (
    CompositeIntent, PlacementAuthority, PlacementRefused, QualifiedHost,
    expected_result, checkpoint_record,
)
from mailcpu.active_host_formation import FormationPolicy, LocalInterpreterSurface
from mailcpu.capability_construction import (
    ACTIVATE, APPLY, COMPOSE, STAGE, CapabilityConstructionCompiler,
    ConstructionInventory, ConstructionPolicy, bind_receiving_surface, observe_gate,
)
from mailcpu.composite_host_formation import (
    CompositeFormationController, CompositeFormationRefused,
    ConstructedComputationEndpoint, semantic_intention,
)
from mailcpu.ground_native_realization import TwoPortArithmeticGate
from mailcpu.runtime_qualification import (
    QualificationPolicy, SubprocessQualificationEndpoint, qualify, digest,
    _request,
)
from mailcpu.federated_placement import MutualTLSQualificationEndpoint, FederationRefused

N = 10**12 + 913
TEST_INTENT = CompositeIntent("sab011-composite", 5, 7, 65521, 19, N)


def make_compute(host: str, *, cost: int = 1, base: Path | None = None,
                 engine: str = "gate") -> ConstructedComputationEndpoint:
    """Construct a new mathematical locus from unassembled receiver primitives."""
    if engine == "gate":
        p = TwoPortArithmeticGate(host + ".composition", 65521)
        q = TwoPortArithmeticGate(host + ".application", 65521)
        a = observe_gate(p, locus=host + ".compose", operation=COMPOSE,
                         coordinate=0, lease_until=10**18, cost=cost)
        b = observe_gate(q, locus=host + ".apply", operation=APPLY,
                         coordinate=0, lease_until=10**18, cost=cost)
        form = None
    elif engine == "python":
        assert base is not None
        base.mkdir(parents=True,exist_ok=True)
        surface = LocalInterpreterSurface(host + ".surface", "python", base, sys.executable)
        a = bind_receiving_surface(surface,locus=host+".stage",operation=STAGE,
                coordinate=0,lease_until=10**18,cost=cost)
        b = bind_receiving_surface(surface,locus=host+".activate",operation=ACTIVATE,
                coordinate=0,lease_until=10**18,cost=cost)
        form = FormationPolicy(frozenset({(surface.surface_id,"python")}),10**18)
    else:
        raise ValueError("unknown engine fixture")
    policy = ConstructionPolicy(frozenset({(a.locus,a.operation),(b.locus,b.operation)}),
                                10**18, max_quanta=100000, max_events=256)
    return ConstructedComputationEndpoint(host,CapabilityConstructionCompiler(
        ConstructionInventory((a,b)),policy),formation_policy=form)


def qualified_subprocess(name: str, role: str, root: Path) -> QualifiedHost:
    """Qualify receiver-owned subprocesses; fixture does not claim TLS authentication."""
    argv = [sys.executable,"-m","mailcpu.runtime_qualification_worker",
            "--host",name,"--directory",str(root/name),"--no-compute"]
    if role == "framed_ipc":
        argv.append("--no-storage")
    elif role == "retained_state":
        argv.append("--no-transfer")
    ep = SubprocessQualificationEndpoint(name,tuple(argv),timeout=7)
    policy = QualificationPolicy(frozenset({name}),"sab011-test-observer",40,
            frozenset({"observer",role}),max_calls=3)
    report = qualify(ep,policy,coordinate=5,seed="sab011-subprocess-qualification")
    assert role in report.payload["verified_roles"]
    return QualifiedHost(ep,report.payload,policy)


def placement_authority(*, computations=("compute-a","compute-b"),
                        remote=("relay","store-a","store-b"),expiry=35) -> PlacementAuthority:
    grants = {(host,"affine_mod") for host in computations}
    if "relay" in remote:
        grants.add(("relay","transfer"))
    for host in remote:
        if host.startswith("store-"):
            grants.add((host,"retain"))
            grants.add((host,"retrieve"))
    return PlacementAuthority(frozenset(grants),expiry,max_quanta=5000,max_bytes=8192)


class FormationBridgeTests(unittest.TestCase):
    """End-to-end local role composition using the existing SAB-004 state protocol."""

    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="sab011-units-")
        cls.root=Path(cls.temp.name)
        cls.compute_a=make_compute("compute-a")
        cls.compute_b=make_compute("compute-b",base=cls.root/"formed-b",engine="python")
        cls.hosts={
            "compute-a":cls.compute_a.qualify(coordinate=5,expires_at=40),
            "compute-b":cls.compute_b.qualify(coordinate=5,expires_at=40),
        }
        for name,role in (("relay","framed_ipc"),("store-a","retained_state"),
                          ("store-b","retained_state")):
            cls.hosts[name]=qualified_subprocess(name,role,cls.root)
        cls.grants=placement_authority()
        cls.cost={ ("compute-a","affine_mod"):1, ("compute-b","affine_mod"):20,
                   ("store-a","retain"):1, ("store-b","retain"):3}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def controller(self,host_map=None,authority=None):
        hosts=host_map if host_map is not None else self.hosts
        return CompositeFormationController(hosts,authority or self.grants,
                quanta={k:v for k,v in self.cost.items() if k[0] in hosts})

    def test_qualifies_two_constructed_methods(self):
        self.assertIn("computational_fragment",self.hosts["compute-a"].report["verified_roles"])
        self.assertIn("computational_fragment",self.hosts["compute-b"].report["verified_roles"])
        self.assertEqual(self.compute_a.last_formation["method"],"constructed.gate-algebra")
        self.assertEqual(self.compute_b.last_formation["method"],"formed.python")

    def test_compile_is_semantic_and_cost_selective(self):
        c=self.controller()
        p=c.compile(TEST_INTENT,active_hosts=tuple(self.hosts),coordinate=7)
        self.assertEqual(p.placement.assignment[0],"compute-a")
        self.assertEqual(p.semantic_digest,semantic_intention(TEST_INTENT).fingerprint)
        self.assertTrue(p.formation_digest)

    def test_rehome_from_gates_to_installed_interpreter(self):
        c=self.controller()
        active=tuple(self.hosts)
        first=c.compile(TEST_INTENT,active_hosts=active,coordinate=7)
        remaining=tuple(x for x in active if x!="compute-a")
        with self.assertRaises((PlacementRefused,CompositeFormationRefused)):
            c.execute(TEST_INTENT,first,active_hosts=remaining,coordinate=7)
        second=c.compile(TEST_INTENT,active_hosts=remaining,coordinate=7)
        self.assertEqual(second.placement.assignment[0],"compute-b")
        before=self.compute_b.execution_count
        result=c.execute(TEST_INTENT,second,active_hosts=remaining,coordinate=7,copies=2)
        self.assertGreater(self.compute_b.execution_count,before)
        self.assertEqual(result["result"],expected_result(TEST_INTENT))
        self.assertEqual(set(result["replicas"]),{"store-a","store-b"})
        self.assertEqual(result["construction_evidence"]["method"],"formed.python")
        self.assertFalse(result["quorum_certificate_supplied"])

    def test_store_only_recovery_never_calls_constructed_host(self):
        c=self.controller()
        remaining=tuple(x for x in self.hosts if x!="compute-a")
        plan=c.compile(TEST_INTENT,active_hosts=remaining,coordinate=7)
        c.execute(TEST_INTENT,plan,active_hosts=remaining,coordinate=7,copies=2)
        before_a,before_b=self.compute_a.execution_count,self.compute_b.execution_count
        only_store={k:v for k,v in self.hosts.items() if k.startswith("store-")}
        restarted=self.controller(host_map=only_store)
        resumed=restarted.resume(TEST_INTENT,active_hosts=("store-b",),coordinate=8)
        self.assertEqual(resumed["result"],expected_result(TEST_INTENT))
        self.assertFalse(resumed["reexecuted_computation"])
        self.assertEqual((before_a,before_b),(self.compute_a.execution_count,self.compute_b.execution_count))
        self.assertEqual(resumed["ground"],semantic_intention(TEST_INTENT).ground.fingerprint)

    def test_source_qualified_roles_cannot_grant_local_execution(self):
        narrow=PlacementAuthority(frozenset(x for x in self.grants.granted
                                 if x!=("compute-a","affine_mod") and x!=("compute-b","affine_mod")),35)
        with self.assertRaises(PlacementRefused):
            self.controller(authority=narrow).compile(TEST_INTENT,
                                      active_hosts=tuple(self.hosts),coordinate=7)

    def test_live_primitive_change_invalidates_compiled_route(self):
        c=self.controller()
        active=tuple(self.hosts)
        plan=c.compile(TEST_INTENT,active_hosts=active,coordinate=7)
        original=self.compute_a.compiler.authority
        try:
            self.compute_a.compiler.authority=replace(original,max_quanta=original.max_quanta-1)
            with self.assertRaises(CompositeFormationRefused):
                c.execute(TEST_INTENT,plan,active_hosts=active,coordinate=7)
        finally:
            self.compute_a.compiler.authority=original

    def test_prepared_checkpoint_without_decision_is_not_recovered(self):
        """Data alone cannot advance SAB-004's existing acceptance predicate."""
        unfinished = CompositeIntent("sab011-uncommitted",5,7,65521,19,N)
        c = self.controller()
        data = checkpoint_record(unfinished,expected_result(unfinished))
        c.placement._store("store-a",unfinished,data)
        with self.assertRaises(PlacementRefused):
            c.resume(unfinished,active_hosts=("store-a",),coordinate=8)

    def test_wrong_ground_conflicts_with_immutable_checkpoint(self):
        c=self.controller()
        active=tuple(x for x in self.hosts if x!="compute-a")
        p=c.compile(TEST_INTENT,active_hosts=active,coordinate=7)
        c.execute(TEST_INTENT,p,active_hosts=active,coordinate=7,copies=2)
        different=CompositeIntent(TEST_INTENT.request_id,3,7,65521,19,N)
        with self.assertRaises(PlacementRefused):
            self.controller(host_map={k:v for k,v in self.hosts.items() if k.startswith("store-")}).resume(
                different,active_hosts=("store-b",),coordinate=8)

    def test_replay_token_cannot_switch_request_meaning(self):
        ep=make_compute("nonce-test")
        req=_request("nonce-test","observe",{"word":"sab003:observe:hello"},"sab011-fixture",0)
        first=ep.exchange(req,max_bytes=4096)
        self.assertEqual(first,ep.exchange(req,max_bytes=4096))
        switched={**req,"payload":{"word":"other"}}
        with self.assertRaises(CompositeFormationRefused):
            ep.exchange(switched,max_bytes=4096)

    def test_no_dynamic_source_dispatch(self):
        ep=make_compute("no-code")
        req=_request("no-code","execute_source",{"source":"print('no')"},"sab011-fixture",1)
        result=ep.exchange(req,max_bytes=4096)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"],"unsupported")

    def test_expired_qualification_and_lease_refused(self):
        c=self.controller()
        with self.assertRaises(PlacementRefused):
            c.compile(TEST_INTENT,active_hosts=tuple(self.hosts),coordinate=41)





@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for direct-peer mTLS test")
class AuthenticatedCompositeTests(unittest.TestCase):
    """Use independent mTLS relay/store listener processes and fresh durable readback."""

    @classmethod
    def _openssl(cls,*args):
        subprocess.run(("openssl",*args),check=True,capture_output=True)

    @classmethod
    def _cert(cls,name):
        key=cls.root/(name+".key")
        csr=cls.root/(name+".csr")
        crt=cls.root/(name+".crt")
        cls._openssl("req","-new","-newkey","rsa:2048","-nodes",
                     "-subj",f"/CN={name}.sab011.test","-keyout",str(key),"-out",str(csr))
        ext=cls.root/(name+".ext")
        usage="clientAuth" if name in {"origin","intruder"} else "serverAuth"
        ext.write_text(f"subjectAltName=DNS:{name}.sab011.test\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage={usage}\n")
        cls._openssl("x509","-req","-in",str(csr),"-CA",str(cls.ca),
                     "-CAkey",str(cls.root/"ca.key"),"-CAcreateserial",
                     "-days","1","-extfile",str(ext),"-out",str(crt))
        return crt,key

    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="sab011-mtls-")
        cls.root=Path(cls.temp.name)
        cls.ca=cls.root/"ca.crt"
        cls._openssl("req","-x509","-newkey","rsa:2048","-nodes",
                     "-days","1","-subj","/CN=SAB011-CA",
                     "-addext","basicConstraints=critical,CA:TRUE",
                     "-addext","keyUsage=critical,keyCertSign,cRLSign",
                     "-keyout",str(cls.root/"ca.key"),"-out",str(cls.ca))
        cls.certs={name:cls._cert(name) for name in
                   ("origin","intruder","relay","store-a","store-b")}
        cls.procs={}
        cls.endpoints={}
        cls.ops={"relay":("observe","transfer"),
                 "store-a":("observe","retain","retrieve"),
                 "store-b":("observe","retain","retrieve")}
        for name in cls.ops:cls._launch(name)
        cls.local=make_compute("compute-local")
        cls.hosts={"compute-local":cls.local.qualify(coordinate=5,expires_at=40)}
        for name,role in (("relay","framed_ipc"),("store-a","retained_state"),
                          ("store-b","retained_state")):
            cls.hosts[name]=cls._qualified_remote(name,role)

    @classmethod
    def _stop(cls,name):
        proc=cls.procs.pop(name,None)
        if proc:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait(timeout=5)
            if proc.stderr:proc.stderr.close()

    @classmethod
    def _launch(cls,name):
        cls._stop(name)
        cert,key=cls.certs[name]
        with socket.socket() as s:
            s.bind(("127.0.0.1",0))
            port=s.getsockname()[1]
        ready=cls.root/(name+".ready")
        ready.unlink(missing_ok=True)
        storage=cls.root/(name+"-state")
        storage.mkdir(exist_ok=True)
        argv=[sys.executable,"-m","mailcpu.federated_placement","serve",
            "--host-id",name,"--listen-address","127.0.0.1","--port",str(port),
            "--certificate",str(cert),"--key",str(key),"--ca-file",str(cls.ca),
            "--client-dns","origin.sab011.test", "--storage-directory",str(storage),
            "--ready-file",str(ready)]
        for op in cls.ops[name]:argv.extend(("--allow",op))
        cls.procs[name]=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        stop=time.monotonic()+12
        while not ready.exists() and time.monotonic()<stop:
            if cls.procs[name].poll() is not None:
                raise AssertionError("listener exited: "+cls.procs[name].stderr.read().decode()[:1500])
            time.sleep(0.04)
        if not ready.exists():raise AssertionError("listener startup deadline exceeded")
        client_cert,client_key=cls.certs["origin"]
        cls.endpoints[name]=MutualTLSQualificationEndpoint(
            name,("127.0.0.1",port),server_dns=name+".sab011.test",
            client_certificate=str(client_cert),client_key=str(client_key),ca_file=str(cls.ca))

    @classmethod
    def _qualified_remote(cls,name,role):
        policy=QualificationPolicy(frozenset({name}),"sab011-mtls-observer",40,
                frozenset({"observer",role}),max_calls=3)
        report=qualify(cls.endpoints[name],policy,coordinate=5,seed="sab011-mtls-authenticated")
        assert role in report.payload["verified_roles"]
        return QualifiedHost(cls.endpoints[name],report.payload,policy)

    @classmethod
    def tearDownClass(cls):
        for name in list(cls.procs):cls._stop(name)
        cls.temp.cleanup()

    def _controller(self,hosts):
        grants=frozenset({("compute-local","affine_mod"),("relay","transfer"),
                ("store-a","retain"),("store-a","retrieve"),
                ("store-b","retain"),("store-b","retrieve")})
        return CompositeFormationController(hosts,PlacementAuthority(grants,35,
               max_quanta=5000,max_bytes=8192))

    def test_mtls_roles_and_restarted_survivor_preserve_formed_ground(self):
        c=self._controller(self.hosts)
        active=tuple(self.hosts)
        plan=c.compile(TEST_INTENT,active_hosts=active,coordinate=7)
        completed=c.execute(TEST_INTENT,plan,active_hosts=active,coordinate=7,copies=2)
        self.assertEqual(completed["result"],expected_result(TEST_INTENT))
        self.assertEqual(set(completed["replicas"]),{"store-a","store-b"})
        before=self.local.execution_count
        self._stop("relay")
        self._stop("store-a")
        self._launch("store-b")
        try:
            restored_hosts={"store-a":self.hosts["store-a"],
                            "store-b":QualifiedHost(self.endpoints["store-b"],
                                self.hosts["store-b"].report,self.hosts["store-b"].policy)}
            resumed=self._controller(restored_hosts).resume(TEST_INTENT,
                                    active_hosts=("store-b",),coordinate=8)
            self.assertFalse(resumed["reexecuted_computation"])
            self.assertEqual(resumed["result"],completed["result"])
            self.assertEqual(self.local.execution_count,before)
        finally:
            self._launch("relay")
            self._launch("store-a")

    def test_mtls_wrong_client_identity_does_not_acquire_retain(self):
        ep=self.endpoints["store-a"]
        cert,key=self.certs["intruder"]
        intruder=MutualTLSQualificationEndpoint("store-a",ep.address,server_dns=ep.server_dns,
                client_certificate=str(cert),client_key=str(key),ca_file=str(self.ca))
        with self.assertRaises(FederationRefused):
            intruder.exchange(_request("store-a","observe",{"word":"x"},"attacker-seed",1),
                              max_bytes=4096)

    def test_receiver_refuses_computation_on_storage_only_role(self):
        request=_request("store-b","affine_mod",TEST_INTENT.input(),"sab011-wrong-op",0)
        answer=self.endpoints["store-b"].exchange(request,max_bytes=4096)
        self.assertEqual((answer["ok"],answer["error"]),(False,"unsupported"))


if __name__ == "__main__":
    unittest.main()
