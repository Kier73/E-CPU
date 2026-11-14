"""SAB-012 true receiver-native/mTLS formation plus native recovery lineage.

The mandatory CI scenario uses multiple independently restarted processes and
three distinct fsynced quorum journals on one test machine. It does not claim
independent physical hosts, independent failure domains, or Byzantine safety.
"""
from __future__ import annotations

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
    CompositeIntent, PlacementAuthority, QualifiedHost, expected_result,
)
from mailcpu.federated_placement import (
    MutualTLSQualificationEndpoint, FederationRefused,
)
from mailcpu.receiver_formed_native import AttestedFormedEndpoint
from mailcpu.runtime_qualification import QualificationPolicy, qualify, _request, digest

try:
    from mailcpu import (
        HeadlessOS, RecoveryLineageCoordinator, RecoveryLineageAuthority,
        RecoveryLineageError, SeedCommitMembership,
    )
    from mailcpu.receiver_formed_quorum import (
        FormedFederatedController, FormedQuorumAnchor,
        FormedQuorumRefused,
    )
    HAVE_NATIVE = HeadlessOS is not None
except ImportError:
    HAVE_NATIVE = False

INTENT=CompositeIntent("sab012-one-ground", 5,7,65521,19,10**12+913)


@unittest.skipUnless(HAVE_NATIVE and shutil.which("openssl"),
                     "Native E-CPU, its recovery lineage, and OpenSSL required")
class FederatedFormationQuorumTests(unittest.TestCase):
    @classmethod
    def openssl(cls,*args):
        subprocess.run(("openssl",*args),check=True,capture_output=True)

    @classmethod
    def cert(cls,name):
        key,csr,crt=(cls.root/(name+ext) for ext in (".key",".csr",".crt"))
        cls.openssl("req","-new","-newkey","rsa:2048","-nodes",
            "-subj",f"/CN={name}.sab012.test","-keyout",str(key),"-out",str(csr))
        ext=cls.root/(name+".ext")
        use="clientAuth" if name in ("origin", "intruder") else "serverAuth"
        ext.write_text(f"subjectAltName=DNS:{name}.sab012.test\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage={use}\n")
        cls.openssl("x509","-req","-in",str(csr),"-CA",str(cls.ca),
            "-CAkey",str(cls.root/"ca.key"),"-CAcreateserial",
            "-days","1","-extfile",str(ext),"-out",str(crt))
        return crt,key

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="sab012-quorum-")
        cls.root = Path(cls.temp.name)
        cls.ca = cls.root/"ca.crt"
        cls.openssl("req","-x509","-newkey","rsa:2048","-nodes",
            "-days","1","-subj","/CN=SAB012-local-CA",
            "-addext","basicConstraints=critical,CA:TRUE",
            "-addext","keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",str(cls.root/"ca.key"),"-out",str(cls.ca))
        cls.certs={name:cls.cert(name) for name in
            ("origin","intruder","compute-formed","relay","store-a","store-b")}
        cls.procs={}
        cls.endpoints={}
        cls.ops={
            "compute-formed":("observe","affine_mod"),
            "relay":("observe","transfer"),
            "store-a":("observe","retain","retrieve"),
            "store-b":("observe","retain","retrieve"),
        }
        try:
            for name in cls.ops:
                cls.launch(name)
            cls.hosts={}
            for name,role in (
                ("compute-formed","computational_fragment"),
                ("relay","framed_ipc"),
                ("store-a","retained_state"),
                ("store-b","retained_state"),
            ):
                ep=(AttestedFormedEndpoint(cls.endpoints[name]) if name=="compute-formed"
                    else cls.endpoints[name])
                policy=QualificationPolicy(frozenset({name}),"sab012-native-quorum-observer",40,
                    frozenset({"observer",role}),
                    max_calls=4 if name=="compute-formed" else 3)
                report=qualify(ep,policy,coordinate=5,
                    seed="sab012-native-qualified-roles")
                assert role in report.payload["verified_roles"]
                cls.hosts[name]=QualifiedHost(ep,report.payload,policy)
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def stop(cls,name):
        proc=cls.procs.pop(name,None)
        if proc is not None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait(timeout=5)
            if proc.stderr:proc.stderr.close()

    @classmethod
    def launch(cls,name):
        cls.stop(name)
        with socket.socket() as s:
            s.bind(("127.0.0.1",0))
            port=s.getsockname()[1]
        ready=cls.root/(name+".ready")
        ready.unlink(missing_ok=True)
        cert,key=cls.certs[name]
        directory=cls.root/(name+"-state")
        directory.mkdir(exist_ok=True)
        if name=="compute-formed":
            args=[sys.executable,"-m","mailcpu.receiver_formed_native","serve",
                "--a","5","--c","7","--mod","65521","--x0","19", "--allow-formation-proof"]
        else:
            args=[sys.executable,"-m","mailcpu.federated_placement","serve"]
        args.extend(["--host-id",name,"--listen-address","127.0.0.1",
            "--port",str(port),"--certificate",str(cert),"--key",str(key),
            "--ca-file",str(cls.ca),"--client-dns","origin.sab012.test",
            "--storage-directory",str(directory),"--ready-file",str(ready)])
        for op in cls.ops[name]:args.extend(("--allow",op))
        cls.procs[name]=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        stop=time.monotonic()+15
        while not ready.exists() and time.monotonic()<stop:
            if cls.procs[name].poll() is not None:
                raise AssertionError("listener failed: "+cls.procs[name].stderr.read().decode()[:1300])
            time.sleep(.04)
        if not ready.exists():
            raise AssertionError("listener startup timeout: "+name)
        origin,key=cls.certs["origin"]
        cls.endpoints[name]=MutualTLSQualificationEndpoint(
            name,("127.0.0.1",port),server_dns=name+".sab012.test",
            client_certificate=str(origin),client_key=str(key),ca_file=str(cls.ca),
            timeout=22)

    @classmethod
    def tearDownClass(cls):
        for name in list(getattr(cls,"procs",{})):
            cls.stop(name)
        if hasattr(cls,"temp"):
            cls.temp.cleanup()

    @classmethod
    def authority(cls):
        return PlacementAuthority(frozenset({
            ("compute-formed","affine_mod"),("relay","transfer"),
            ("store-a","retain"),("store-a","retrieve"),
            ("store-b","retain"),("store-b","retrieve"),
        }),35,max_quanta=5000,max_bytes=8192)

    @classmethod
    def coordinator(cls):
        member=SeedCommitMembership("sab012-machine",1,("A","B","C"),"A",1,
                 digest({"schema":"sab012.genesis"}))
        root=cls.root/"quorum"
        root.mkdir(exist_ok=True)
        participants={name:RecoveryLineageAuthority(member,name,root/(name+".jsonl"))
            for name in member.member_ids}
        return RecoveryLineageCoordinator(member,participants)

    def test_receiver_native_formation_through_replication_and_quorum(self):
        controller=FormedFederatedController(self.hosts,self.authority())
        active=tuple(self.hosts)
        plan=controller.compile(INTENT,active_hosts=active,coordinate=7)
        self.assertEqual(plan.compute_host,"compute-formed")
        completed=controller.execute(INTENT,plan,active_hosts=active,coordinate=7,copies=2)
        self.assertEqual(completed["result"],expected_result(INTENT))
        self.assertEqual(set(completed["replicas"]),{"store-a","store-b"})
        self.assertEqual(completed["formed_receiver_audit"]["evidence"]["hypervisor_action"],"allow")

        recovery_root=self.root/"recovery-state"
        recovery_root.mkdir(exist_ok=True)
        anchor=FormedQuorumAnchor(self.coordinator(),recovery_root)
        sealed=anchor.seal(INTENT,completed,controller=controller,
            active_hosts=active,coordinate=8,generation=1)
        self.assertTrue(sealed["quorum_sealed"])
        self.assertGreaterEqual(len(sealed["native_proof"]["decisions"]),2)

        # The computing and forwarding processes are now gone. One storage
        # replica also disappears, and a different controller recovers solely
        # from the surviving peer plus the independent quorum journals.
        for name in ("compute-formed","relay","store-a"):
            self.stop(name)
        self.stop("store-b")
        self.launch("store-b")
        survivor=QualifiedHost(self.endpoints["store-b"],
            self.hosts["store-b"].report,self.hosts["store-b"].policy)
        isolated=FormedFederatedController({"store-a":self.hosts["store-a"],
            "store-b":survivor},self.authority())
        before=isolated.resume(INTENT,active_hosts=("store-b",),coordinate=9)
        self.assertFalse(before["reexecuted_computation"])
        self.assertEqual(before["result"],completed["result"])
        restored=FormedQuorumAnchor(self.coordinator(),recovery_root).recover(INTENT,generation=1)
        self.assertTrue(restored["quorum_sealed"])
        self.assertFalse(restored["reexecuted_computation"])
        self.assertEqual(restored["result"],completed["result"])

        # An older generation cannot supersede the current high-water root;
        # a changed Ground cannot borrow this state or its majority seal.
        with self.assertRaises((FormedQuorumRefused,RecoveryLineageError)):
            anchor.seal(INTENT,completed,controller=isolated,
                active_hosts=("store-b",),coordinate=9,generation=1)
        wrong=CompositeIntent(INTENT.request_id,3,7,65521,19,INTENT.coordinate)
        with self.assertRaises((FormedQuorumRefused,RecoveryLineageError)):
            FormedQuorumAnchor(self.coordinator(),recovery_root).recover(wrong,generation=1)

        # Native data integrity is required *in addition* to the quorum proof.
        file=recovery_root/"state-1.json"
        original=file.read_bytes()
        file.write_bytes(original.replace(b'"value":46511',b'"value":46512'))
        try:
            with self.assertRaises((FormedQuorumRefused,RecoveryLineageError)):
                FormedQuorumAnchor(self.coordinator(),recovery_root).recover(INTENT,generation=1)
        finally:
            file.write_bytes(original)
        for name in ("compute-formed","relay","store-a"):
            self.launch(name)

    def test_wrong_client_certificate_and_storage_not_compute(self):
        cert,key=self.certs["intruder"]
        ep=self.endpoints["compute-formed"]
        intruder=MutualTLSQualificationEndpoint(
            "compute-formed",ep.address,server_dns=ep.server_dns,
            client_certificate=str(cert),client_key=str(key),ca_file=str(self.ca))
        with self.assertRaises(FederationRefused):
            intruder.exchange(_request("compute-formed","affine_mod",
                INTENT.input(),"sab012-intruder",1),max_bytes=4096)
        storage=self.endpoints["store-b"]
        result=storage.exchange(_request("store-b","affine_mod",
            INTENT.input(),"sab012-unauthorized",1),max_bytes=4096)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"],"unsupported")


if __name__ == "__main__":
    unittest.main()