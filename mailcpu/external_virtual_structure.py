"""HSS-002: host external model *structure* as a navigable Virtual Layer Ground.

No model data is fetched. The source host keeps all tensors and artifacts.
The only network calls permitted in this module are to a metadata API
describing immutable repository revision, file names/sizes and optional
architecture configuration. The resulting virtual processor executes
source-structural intentions without transferring a source file or range.

An address is not evidence of trained numerical values. Neural behavior can
be asserted only by separately qualified source-local observers or laws.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SCHEMA = "mailcpu.external-virtual-structure.v1"
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
PATH = re.compile(r"[A-Za-z0-9_.+@/-]{1,1024}\Z")
MAX_META = 2*1024*1024
MAX_FILES = 10000
OPS = frozenset(("source.catalogue","source.file","source.extent",
                 "source.architecture","source.layer"))


class StructureRefused(ValueError):
    """A source observation or virtual execution lacks its required Ground."""


def canonical(value:Any)->bytes:
    try:
        return json.dumps(value,sort_keys=True,separators=(",",":"),
                          ensure_ascii=False,allow_nan=False).encode()
    except (TypeError,ValueError) as exc:
        raise StructureRefused("noncanonical source structure") from exc


def digest(value:Any)->str:
    return sha256(canonical(value)).hexdigest()


def safe_path(path:str)->str:
    if (type(path) is not str or PATH.fullmatch(path) is None
        or path.startswith("/") or "//" in path
        or any(part in (".","..") for part in path.split("/"))):
        raise StructureRefused("source path cannot be interpreted")
    return path


def metadata_url(url:str)->str:
    """Qualify an exact public metadata API URL. /resolve is never allowed."""
    if type(url) is not str or len(url)>4096:
        raise StructureRefused("invalid metadata URL")
    p=urlsplit(url)
    if (p.scheme!="https" or p.netloc!="huggingface.co" or p.fragment
        or not p.path.startswith("/api/models/")
        or any(s in (".","..","resolve","blob") for s in p.path.split("/"))):
        raise StructureRefused("requested URL is not an approved metadata observation")
    return url


def strict_json(raw:bytes,wanted:type)->Any:
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d: raise StructureRefused("duplicate metadata field")
            d[k]=v
        return d
    try:
        v=json.loads(raw,object_pairs_hook=unique,
                     parse_constant=lambda _:(_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError,UnicodeError) as exc:
        raise StructureRefused("source metadata JSON invalid") from exc
    if type(v) is not wanted:
        raise StructureRefused("source metadata type differs")
    return v


@dataclass(frozen=True)
class MetadataObservation:
    """Only metadata bytes, never model data bytes or file content."""
    body:bytes
    headers:Mapping[str,str]=field(default_factory=dict)
    status:int=200
    def __post_init__(self):
        if (type(self.body) is not bytes or not 0<len(self.body)<=MAX_META
            or not isinstance(self.headers,Mapping) or self.status!=200):
            raise StructureRefused("metadata observation invalid")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise StructureRefused("metadata redirect changed source identity")


class HTTPSMetadataObserver:
    """Receiver-controlled metadata-only HTTPS observer (no weight read method)."""
    def __init__(self,timeout:float=10.0):
        if type(timeout) not in (int,float) or not 0<float(timeout)<=30:
            raise StructureRefused("invalid metadata observer timeout")
        self.timeout=float(timeout)
        self.metadata_bytes=0
        self.calls=0
    def read_metadata(self,url:str)->MetadataObservation:
        metadata_url(url)
        opener=build_opener(_NoRedirect,HTTPSHandler())
        request=Request(url,method="GET",headers={
            "Accept":"application/json","Accept-Encoding":"identity",
            "User-Agent":"E-CPU-Virtual-Structure-Observer"})
        try:
            with opener.open(request,timeout=self.timeout) as response:
                raw=response.read(MAX_META+1)
                result=MetadataObservation(raw,dict((k.lower(),v)
                                                    for k,v in response.headers.items()),
                                           response.status)
        except (HTTPError,URLError,TimeoutError,OSError) as exc:
            raise StructureRefused("metadata observer failed to read source") from exc
        self.calls+=1
        self.metadata_bytes+=len(raw)
        return result


def source_page(url:str)->tuple[str,str]:
    p=urlsplit(url)
    if p.scheme!="https" or p.netloc!="huggingface.co" or p.query or p.fragment:
        raise StructureRefused("unadmitted source page URL")
    bits=p.path.strip("/").split("/")
    if len(bits)!=4 or bits[2]!="tree":
        raise StructureRefused("source page must be an explicit tree")
    repo="/".join(bits[:2])
    if REPO.fullmatch(repo) is None or not(bits[3]=="main" or SHA40.fullmatch(bits[3])):
        raise StructureRefused("source repository or revision malformed")
    return repo,bits[3]


@dataclass(frozen=True)
class RemoteFile:
    """A physical object remains entirely at the source; only its name is held."""
    path:str
    size_bytes:int
    source_sha256:str|None=None
    def __post_init__(self):
        safe_path(self.path)
        if (type(self.size_bytes) is not int or self.size_bytes<0
            or self.source_sha256 is not None
            and (type(self.source_sha256) is not str
                 or SHA64.fullmatch(self.source_sha256) is None)):
            raise StructureRefused("malformed source file extent")
    def to_dict(self):
        return {"path":self.path,"size_bytes":self.size_bytes,
                "source_sha256":self.source_sha256}


@dataclass(frozen=True)
class SourceStructure:
    """A compact virtual Ground of static addresses, not model weight storage."""
    repository:str
    revision:str
    files:tuple[RemoteFile,...]
    config:Mapping[str,Any]=field(default_factory=dict)
    observation_digests:tuple[str,...]=()
    _index:Mapping[str,RemoteFile]=field(init=False,repr=False,compare=False)
    _size:int=field(init=False,repr=False,compare=False)
    _head:str=field(init=False,repr=False,compare=False)

    def __post_init__(self):
        if (type(self.repository) is not str or REPO.fullmatch(self.repository) is None
            or type(self.revision) is not str or SHA40.fullmatch(self.revision) is None
            or type(self.files) is not tuple or len(self.files)>MAX_FILES
            or any(not isinstance(f,RemoteFile) for f in self.files)
            or tuple(sorted(self.files,key=lambda f:f.path))!=self.files
            or len({f.path for f in self.files})!=len(self.files)
            or type(self.observation_digests) is not tuple
            or any(type(d) is not str or SHA64.fullmatch(d) is None
                   for d in self.observation_digests)):
            raise StructureRefused("virtual source catalogue invalid")
        if not isinstance(self.config,Mapping):
            raise StructureRefused("model configuration description invalid")
        config=strict_json(canonical(dict(self.config)),dict)
        if len(canonical(config))>16384:
            raise StructureRefused("description exceeds structural observation budget")
        object.__setattr__(self,"config",MappingProxyType(config))
        object.__setattr__(self,"_index",MappingProxyType({f.path:f for f in self.files}))
        object.__setattr__(self,"_size",sum(f.size_bytes for f in self.files))
        object.__setattr__(self,"_head",digest(self.to_dict()))

    @property
    def declared_bytes(self)->int: return self._size

    def file(self,path:str)->RemoteFile:
        try: return self._index[safe_path(path)]
        except KeyError as exc:
            raise StructureRefused("source address absent") from exc

    def to_dict(self)->dict:
        return {"schema":SCHEMA+".source",
                "repository":self.repository,"revision":self.revision,
                "files":[f.to_dict() for f in self.files],
                "config":dict(self.config),
                "observation_digests":list(self.observation_digests),
                "scope":"external_structure_only_zero_model_payload"}

    @property
    def ground_digest(self)->str:return self._head

    @classmethod
    def restore(cls,document:Mapping[str,Any],expected_head:str)->"SourceStructure":
        if (not isinstance(document,Mapping) or type(expected_head) is not str
            or SHA64.fullmatch(expected_head) is None or digest(document)!=expected_head
            or set(document)!={"schema","repository","revision","files","config",
                                "observation_digests","scope"}
            or document["schema"]!=SCHEMA+".source"
            or document["scope"]!="external_structure_only_zero_model_payload"):
            raise StructureRefused("source snapshot identity not independently accepted")
        try:
            obj=cls(document["repository"],document["revision"],
                    tuple(RemoteFile(**f) for f in document["files"]),
                    document["config"],tuple(document["observation_digests"]))
        except (KeyError,TypeError) as exc:
            raise StructureRefused("source snapshot malformed") from exc
        if obj.to_dict()!=document:
            raise StructureRefused("source Ground changed on restore")
        return obj


class MetadataNavigator:
    """Translate source metadata into stable virtual structure without payload."""
    def __init__(self,observer:Any):
        if not callable(getattr(observer,"read_metadata",None)):
            raise StructureRefused("no authorized metadata observer")
        self.observer=observer

    def discover(self,page:str,*,max_pages:int=16)->SourceStructure:
        repo,ref=source_page(page)
        if type(max_pages) is not int or not 1<=max_pages<=32:
            raise StructureRefused("metadata traversal budget invalid")
        root=f"https://huggingface.co/api/models/{repo}"
        if ref!="main":root+="/revision/"+ref
        obs=self.observer.read_metadata(metadata_url(root))
        info=strict_json(obs.body,dict)
        sha=info.get("sha")
        if type(sha) is not str or SHA40.fullmatch(sha) is None or ref!="main" and ref!=sha:
            raise StructureRefused("source revision cannot be pinned")
        # Source-host declarations only; no model-family execution assumptions.
        conf=info.get("config") or {}
        if type(conf) is not dict:
            raise StructureRefused("configuration description malformed")
        admitted=frozenset(("model_type","architectures","num_hidden_layers","n_layer",
                             "hidden_size","n_embd","num_attention_heads",
                             "num_key_value_heads","num_experts","num_experts_per_tok",
                             "layer_types","vocab_size"))
        config={k:v for k,v in conf.items() if k in admitted}
        visited=set()
        address=f"https://huggingface.co/api/models/{repo}/tree/{sha}?recursive=true"
        found={}
        observations=[sha256(obs.body).hexdigest()]
        for _ in range(max_pages):
            if address in visited:raise StructureRefused("metadata pagination cycle")
            visited.add(address)
            page_obs=self.observer.read_metadata(metadata_url(address))
            observations.append(sha256(page_obs.body).hexdigest())
            for item in strict_json(page_obs.body,list):
                if type(item) is not dict:
                    raise StructureRefused("malformed source tree entry")
                if item.get("type")=="directory":continue
                if item.get("type")!="file":
                    raise StructureRefused("unsupported metadata entry type")
                lfs=item.get("lfs")
                file=RemoteFile(item.get("path"),item.get("size"),
                                lfs.get("sha256") if type(lfs) is dict else None)
                if file.path in found and found[file.path]!=file:
                    raise StructureRefused("source inventory contains contradictory coordinates")
                found[file.path]=file
                if len(found)>MAX_FILES:raise StructureRefused("metadata file budget exceeded")
            nxt=None
            for entry in page_obs.headers.get("link","").split(","):
                if 'rel="next"' in entry:
                    m=re.search(r"<([^<>]+)>",entry)
                    if m:nxt=urljoin(address,m.group(1))
            if nxt is None:break
            p=urlsplit(nxt)
            if (p.scheme!="https" or p.netloc!="huggingface.co"
                or p.path!=urlsplit(address).path):
                raise StructureRefused("pagination escaped pinned source")
            address=metadata_url(nxt)
        else:raise StructureRefused("metadata page budget exceeded")
        return SourceStructure(repo,sha,tuple(sorted(found.values(),key=lambda f:f.path)),
                               config,tuple(observations))


def _resolve(source:SourceStructure,operation:str,args:dict)->dict:
    """Pure structural semantics: every output follows from admitted metadata."""
    if operation=="source.catalogue":
        if args:raise StructureRefused("catalogue takes no arguments")
        ext={}
        for f in source.files:
            x=f.path.rsplit(".",1)[-1] if "." in f.path else "unknown"
            ext[x]=ext.get(x,0)+1
        return {"files":len(source.files),"declared_external_bytes":source.declared_bytes,
                "file_extensions":dict(sorted(ext.items()))}
    if operation=="source.architecture":
        if args:raise StructureRefused("architecture takes no arguments")
        return {"observed_configuration":dict(source.config),
                "semantics":"source_declared_only"}
    if operation=="source.file":
        if set(args)!={"path"}:raise StructureRefused("file lookup needs path")
        f=source.file(args["path"])
        return {"address":f"hf://{source.repository}@{source.revision}/{f.path}",
                "declared_size_bytes":f.size_bytes,"source_sha256":f.source_sha256}
    if operation=="source.extent":
        if set(args)!={"path","offset","length"}:
            raise StructureRefused("extent needs path,offset,length")
        f=source.file(args["path"])
        off,n=args["offset"],args["length"]
        if (type(off) is not int or type(n) is not int or off<0
            or n<=0 or off+n>f.size_bytes):
            raise StructureRefused("virtual coordinate exceeds external file")
        return {"address":f"hf://{source.repository}@{source.revision}/{f.path}",
                "offset":off,"length":n,"end":off+n,
                "model_payload_bytes_read":0,
                "meaning":"virtual_source_coordinate_not_tensor_values"}
    if operation=="source.layer":
        if set(args)!={"index"} or type(args.get("index")) is not int:
            raise StructureRefused("layer intention needs integer index")
        count=source.config.get("num_hidden_layers",source.config.get("n_layer"))
        if type(count) is not int or count<1:
            raise StructureRefused("layer structure is not source-declared")
        if args["index"]<0 or args["index"]>=count:
            raise StructureRefused("layer index outside observed architecture")
        return {"layer_index":args["index"],"declared_layers":count,
                "model_type":source.config.get("model_type"),
                "meaning":"abstract_layer_coordinate_not_neural_execution"}
    raise StructureRefused("interpreter has no law for requested behavior")


@dataclass(frozen=True)
class VirtualRead:
    """One realized structural behavior, independent of physical model size."""
    record:Mapping[str,Any]
    @property
    def digest(self)->str:return self.record["position_digest"]
    def to_dict(self)->dict:return dict(self.record)
    @classmethod
    def restore(cls,source:SourceStructure,record:Mapping[str,Any],
                expected_head:str)->"VirtualRead":
        if not isinstance(record,Mapping) or record.get("position_digest")!=expected_head:
            raise StructureRefused("position head differs after observer migration")
        other=compile_virtual_read(source,record.get("operation"),record.get("arguments"))
        if other.to_dict()!=record:
            raise StructureRefused("source-relative virtual read cannot reconstruct")
        return other


def compile_virtual_read(source:SourceStructure,operation:str,
                         arguments:Mapping[str,Any]|None=None)->VirtualRead:
    """Interpret an intention and publish control frames, never data frames."""
    if (not isinstance(source,SourceStructure) or type(operation) is not str
        or operation not in OPS or arguments is not None
        and not isinstance(arguments,Mapping)):
        raise StructureRefused("unadmitted virtual model operation")
    args=dict(arguments or {})
    if len(canonical(args))>4096:raise StructureRefused("intention too large")
    result=_resolve(source,operation,args)
    head=digest({"schema":SCHEMA+".genesis","source_head":source.ground_digest})
    frames=[]
    for index,(kind,desc) in enumerate((
        ("ground.source",{"source_head":source.ground_digest}),
        ("ground.intention",{"operation":operation,"arguments":args}),
        ("ground.realization",{"result_digest":digest(result)}),
    )):
        step={"index":index,"kind":kind,"description":desc,"predecessor":head}
        head=digest(step)
        frames.append({**step,"head":head})
    record={"schema":SCHEMA+".position",
            "source_head":source.ground_digest,"operation":operation,
            "arguments":args,"result":result,"frames":frames,
            "model_payload_reads":0,"model_payload_bytes":0,
            "interpretation":"source_structural_intention_only"}
    record["position_digest"]=digest(record)
    return VirtualRead(record)


def project_browser_addresses(page:str,links:Sequence[str],*,origin:str)->dict:
    """Headless-browser *observation adapter* for projected links only.

    The browser host supplies address strings. No DOM, assets, or checkpoint
    are downloaded by the VL or used as executable Python/JS.
    """
    if (type(page) is not str or type(origin) is not str
        or type(links) not in (list,tuple) or len(links)>256
        or urlsplit(page).netloc!=origin or urlsplit(page).scheme!="https"):
        raise StructureRefused("unadmitted browser observation")
    addresses=[]
    for path in links:
        if type(path) is not str or not path or len(path)>2048:
            raise StructureRefused("invalid browser link")
        addr=urljoin(page,path)
        loc=urlsplit(addr)
        if (loc.scheme=="https" and loc.netloc==origin
            and not loc.fragment and addr not in addresses):
            addresses.append(addr)
    result={"schema":SCHEMA+".browser-addresses","page":page,
            "source_origin":origin,"addresses":addresses,
            "model_payload_bytes":0,
            "scope":"projected_external_links_not_webpage_or_model_download"}
    result["ground_digest"]=digest(result)
    return result
