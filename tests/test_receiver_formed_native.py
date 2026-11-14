"""SAB-012 receiver-owned formation wire and native Hypervisor contract tests."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from mailcpu.receiver_formed_native import (
    AttestedFormedEndpoint, ReceiverFormationRefused, PROOF_OPERATION,
    SCHEMA, _check_affine_request, _audit_path, _native_formed_affine, serve_worker,
)
from mailcpu.federated_placement import (
    FederationRefused, MutualTLSQualificationEndpoint,
)
from mailcpu.ground_native_realization import AffineGround
from mailcpu.runtime_qualification import (
    _request, canonical, digest, _check_response, qualify, QualificationPolicy,
)

GROUND = AffineGround(5, 7, 65521, 19)
COORD = 10**12 + 913
PAYLOAD = {"a":5, "c":7, "mod":65521, "x0":19, "coordinate":COORD}

try:
    from mailcpu import HeadlessOS
    HAVE_NATIVE = HeadlessOS is not None
except ImportError:
    HAVE_NATIVE = False


def req(host: str = "compute-formed", op: str = "affine_mod", *, number: int=1):
    payload = PAYLOAD if op == "affine_mod" else {"word":"sab003:observe:hello"}
    return _request(host, op, payload, "sab012-native-receiver", number)


class ContractTests(unittest.TestCase):
    """These run with the portable SAB-008–011 modules alone."""

    def test_strict_ground_and_wire_acceptance(self):
        intention, fingerprint = _check_affine_request(req(), "compute-formed", GROUND)
        self.assertEqual(intention.coordinate, COORD)
        self.assertEqual(fingerprint, digest(req()))

    def test_remote_ground_change_refused(self):
        payload = req()
        payload["payload"] = {**PAYLOAD, "a":4}
        with self.assertRaises(ReceiverFormationRefused):
            _check_affine_request(payload, "compute-formed", GROUND)

    def test_remote_source_and_authority_fields_refused(self):
        for field in ("code", "command", "capability", "formation_authority"):
            with self.subTest(field=field):
                payload = req()
                payload[field] = "print('unauthorized')"
                with self.assertRaises(ReceiverFormationRefused):
                    _check_affine_request(payload, "compute-formed", GROUND)

    def test_boolean_coordinate_and_wrong_host_refused(self):
        payload = req()
        payload["payload"] = {**PAYLOAD, "coordinate":True}
        with self.assertRaises(ReceiverFormationRefused):
            _check_affine_request(payload, "compute-formed", GROUND)
        with self.assertRaises(ReceiverFormationRefused):
            _check_affine_request(req("other"), "compute-formed", GROUND)

    def test_revocation_precedes_local_installation(self):
        with tempfile.TemporaryDirectory() as home:
            for revoked in ("native", "formation"):
                with self.subTest(revoked=revoked):
                    with self.assertRaises(ReceiverFormationRefused):
                        serve_worker(req(), host_id="compute-formed",ground=GROUND,
                            directory=Path(home),
                            native_authority=revoked!="native",
                            formation_authority=revoked!="formation")
                    self.assertFalse((Path(home)/"installed-ground").exists())

    def test_attested_client_rejects_forged_native_evidence(self):
        class ScriptedTLS(MutualTLSQualificationEndpoint):
            def __init__(self, *, bad):
                self.host_id = "compute-formed"
                self.bad = bad
                self.original = None
            def exchange(self, request, *, max_bytes):
                if request["operation"] == "affine_mod":
                    self.original = dict(request)
                    answer = {"value": 46511}
                    reply = {"kind":"mailcpu.sab003.reply.v1","host":self.host_id,
                        "nonce":request["nonce"],"boot":"a"*32,
                        "ok":True,"result":answer,"error":None}
                elif request["operation"] == PROOF_OPERATION:
                    original = self.original
                    expected = digest(original)
                    evidence = {"schema":SCHEMA+".evidence", "ground":GROUND.fingerprint,
                        "coordinate":COORD,"value":46511,"hypervisor_action":"allow",
                        "hypervisor_executed":True,"physical_host_attested":False,
                        "request_digest":expected,
                        "native_operator":"2"*64,
                        "hypervisor_receipt_digest":"3"*64,
                        "formed":{"seed_manifest":"1"*64}}
                    if self.bad == "deny":
                        evidence["hypervisor_action"]="deny"
                    audit = {"schema":SCHEMA+".audit", "host":self.host_id,
                        "request_digest":expected,"ground":GROUND.fingerprint,
                        "result":{"value":46511},"evidence":evidence}
                    audit["digest"] = digest(audit)
                    if self.bad == "digest":
                        audit["digest"]="0"*64
                    reply = {"kind":"mailcpu.sab003.reply.v1","host":self.host_id,
                        "nonce":request["nonce"],"boot":"b"*32,
                        "ok":True,"result":{"audit":audit},"error":None}
                else:
                    raise AssertionError("unexpected operation")
                _check_response(request,reply)
                return reply
        for tamper in ("deny","digest"):
            with self.subTest(tamper=tamper):
                ep = AttestedFormedEndpoint(ScriptedTLS(bad=tamper))
                with self.assertRaises(ReceiverFormationRefused):
                    ep.exchange(req(),max_bytes=4096)
                self.assertIsNone(ep.last_attestation)
        ep = AttestedFormedEndpoint(ScriptedTLS(bad=None))
        self.assertEqual(ep.exchange(req(),max_bytes=4096)["result"],{"value":46511})
        self.assertEqual(ep.last_attestation["ground"],GROUND.fingerprint)


@unittest.skipUnless(HAVE_NATIVE, "Native E-CPU Virtual Layer/Hypervisor required")
class NativeFormingWorkerTests(unittest.TestCase):
    def test_receiver_forms_after_native_admission_then_restarts(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            request = req()
            first = serve_worker(request, host_id="compute-formed",ground=GROUND,
                                 directory=root)
            self.assertEqual(first["result"],{"value":46511})
            path = _audit_path(root,"compute-formed",request["nonce"])
            audit = json.loads(path.read_bytes())
            self.assertEqual(audit["evidence"]["hypervisor_action"],"allow")
            self.assertEqual(audit["evidence"]["formed"]["engine"],"python")
            self.assertTrue((root/"installed-ground"/"ecpu-seed.py").exists())
            again = serve_worker(request,host_id="compute-formed",ground=GROUND,
                                 directory=root)
            self.assertEqual(again["result"],first["result"])
            self.assertNotEqual(again["boot"],first["boot"])
            with self.assertRaises(ReceiverFormationRefused):
                serve_worker(request,host_id="compute-formed",ground=GROUND,
                             directory=root,formation_authority=False)
            # A retained receipt does not admit a corrupted or missing seed.
            (root/"installed-ground"/"ecpu-seed.py").write_text("# tampered")
            with self.assertRaises(ReceiverFormationRefused):
                serve_worker(request, host_id="compute-formed",ground=GROUND,
                             directory=root)

    def test_hypervisor_refusal_does_not_form_interpreter(self):
        with tempfile.TemporaryDirectory() as home:
            with self.assertRaises(ReceiverFormationRefused):
                _native_formed_affine(req(), host_id="compute-formed",
                    ground=GROUND, directory=Path(home), engine="python",
                    native_authority=False, formation_authority=True)
            self.assertFalse((Path(home)/"installed-ground").exists())

    def test_changed_nonce_cannot_change_original_audit(self):
        with tempfile.TemporaryDirectory() as home:
            request = req()
            serve_worker(request,host_id="compute-formed",ground=GROUND,
                         directory=Path(home))
            switched={**request,"payload":{**PAYLOAD,"coordinate":19}}
            with self.assertRaises(ReceiverFormationRefused):
                serve_worker(switched,host_id="compute-formed",ground=GROUND,
                             directory=Path(home))


@unittest.skipUnless(HAVE_NATIVE and shutil.which("openssl"), "Native E-CPU and OpenSSL required")
class NativeMutualTLSTests(unittest.TestCase):
    """One genuinely authenticated TLS process boundary; not a physical host claim."""

    @classmethod
    def openssl(cls,*args):
        subprocess.run(("openssl",*args),check=True,capture_output=True)

    @classmethod
    def cert(cls,name):
        key,csr,crt=(cls.root/(name+ext) for ext in (".key",".csr",".crt"))
        cls.openssl("req","-new","-newkey","rsa:2048","-nodes",
            "-subj",f"/CN={name}.sab012.test","-keyout",str(key),"-out",str(csr))
        ext=cls.root/(name+".ext")
        use="clientAuth" if name in ("origin","intruder") else "serverAuth"
        ext.write_text(f"subjectAltName=DNS:{name}.sab012.test\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage={use}\n")
        cls.openssl("x509","-req","-in",str(csr),"-CA",str(cls.ca),
            "-CAkey",str(cls.root/"ca.key"),"-CAcreateserial",
            "-days","1","-extfile",str(ext),"-out",str(crt))
        return crt,key

    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="sab012-mtls-")
        cls.root=Path(cls.temp.name)
        cls.ca=cls.root/"ca.crt"
        cls.openssl("req","-x509","-newkey","rsa:2048","-nodes",
            "-days","1","-subj","/CN=SAB012-CA",
            "-addext","basicConstraints=critical,CA:TRUE",
            "-addext","keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",str(cls.root/"ca.key"),"-out",str(cls.ca))
        cls.certs={name:cls.cert(name) for name in ("origin","intruder","compute-formed")}
        cls._launch()

    @classmethod
    def _launch(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            port=sock.getsockname()[1]
        cls.ready=cls.root/"compute.ready"
        cls.ready.unlink(missing_ok=True)
        cert,key=cls.certs["compute-formed"]
        argv=[sys.executable,"-m","mailcpu.receiver_formed_native","serve",
            "--host-id","compute-formed","--storage-directory",str(cls.root/"state"),
            "--a","5","--c","7","--mod","65521","--x0","19",
            "--listen-address","127.0.0.1","--port",str(port),
            "--certificate",str(cert),"--key",str(key),"--ca-file",str(cls.ca),
            "--client-dns","origin.sab012.test","--ready-file",str(cls.ready),
            "--allow","observe","--allow","affine_mod", "--allow-formation-proof"]
        (cls.root/"state").mkdir(exist_ok=True)
        cls.proc=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        deadline=time.monotonic()+15
        while not cls.ready.exists() and time.monotonic()<deadline:
            if cls.proc.poll() is not None:
                raise AssertionError("receiver exited: "+cls.proc.stderr.read().decode()[:1200])
            time.sleep(.03)
        if not cls.ready.exists():
            raise AssertionError("formed TLS receiver startup timeout")
        client,key=cls.certs["origin"]
        cls.endpoint=MutualTLSQualificationEndpoint(
            "compute-formed",("127.0.0.1",port),
            server_dns="compute-formed.sab012.test",
            client_certificate=str(client),client_key=str(key),ca_file=str(cls.ca),timeout=20)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill();cls.proc.wait(timeout=5)
        if cls.proc.stderr:cls.proc.stderr.close()
        cls.temp.cleanup()

    def test_mtls_formed_role_and_proof(self):
        ep=AttestedFormedEndpoint(self.endpoint)
        report=qualify(ep,QualificationPolicy(frozenset({"compute-formed"}),
            "sab012-mtls-observer",COORD+10,frozenset({"observer","computational_fragment"}),
            max_calls=4),coordinate=5,seed="sab012-qualified-formed-runtime")
        self.assertIn("computational_fragment",report.payload["verified_roles"])
        got=ep.exchange(req(number=14),max_bytes=4096)
        self.assertEqual(got["result"],{"value":46511})
        self.assertEqual(ep.last_attestation["evidence"]["hypervisor_action"],"allow")

    def test_wrong_tls_client_and_source_dispatch_refused(self):
        cert,key=self.certs["intruder"]
        attacker=MutualTLSQualificationEndpoint(
            "compute-formed",self.endpoint.address,
            server_dns=self.endpoint.server_dns,
            client_certificate=str(cert),client_key=str(key),ca_file=str(self.ca))
        with self.assertRaises(FederationRefused):
            attacker.exchange(req(number=20),max_bytes=4096)
        injected = _request("compute-formed","execute_source",
            {"source":"print('not authorized')"},"sab012-remote-source",1)
        answer=self.endpoint.exchange(injected,max_bytes=4096)
        self.assertEqual((answer["ok"],answer["error"]),(False,"unsupported"))


if __name__ == "__main__":
    unittest.main()