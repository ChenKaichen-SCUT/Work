// Optional CPython accelerator for the same PortStep algebra. No search.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <vector>
#include <utility>
#include <cstdint>
using Bits=unsigned __int128;
using Pair=std::pair<int,int>;
struct Plan {
  int width; bool acyclic;
  std::vector<int> bi,bo,ai,ao;
  std::vector<Pair> tests;
  std::vector<std::vector<Pair>> choices;
};
static std::vector<int> ints(PyObject* obj) {
  std::vector<int> out;
  for(Py_ssize_t i=0;i<PyTuple_GET_SIZE(obj);i++) out.push_back((int)PyLong_AsLong(PyTuple_GET_ITEM(obj,i)));
  return out;
}
static std::vector<Pair> pairs(PyObject* obj) {
  std::vector<Pair> out;
  for(Py_ssize_t i=0;i<PyTuple_GET_SIZE(obj);i++) {
    auto row=PyTuple_GET_ITEM(obj,i);out.emplace_back(PyLong_AsLong(PyTuple_GET_ITEM(row,0)),PyLong_AsLong(PyTuple_GET_ITEM(row,1)));
  }
  return out;
}
static Bits bits(PyObject* obj) {
  auto lo=PyLong_AsUnsignedLongLongMask(obj);
  auto shift=PyLong_FromLong(64);auto high=PyNumber_Rshift(obj,shift);Py_DECREF(shift);
  auto hi=PyLong_AsUnsignedLongLongMask(high);Py_DECREF(high);
  return (Bits(hi)<<64)|lo;
}
static int first(Bits b) {
  auto lo=(uint64_t)b;return lo?__builtin_ctzll(lo):64+__builtin_ctzll((uint64_t)(b>>64));
}
static PyObject* attr(PyObject* obj,const char* name) {return PyObject_GetAttrString(obj,name);}
static void destroy(PyObject* capsule) {delete (Plan*)PyCapsule_GetPointer(capsule,"wmcheck.port");}
static PyObject* prepare(PyObject*,PyObject* obj) {
  auto p=new Plan;
  auto o=attr(obj,"width");p->width=PyLong_AsLong(o);Py_DECREF(o);
  o=attr(obj,"acyclic");p->acyclic=PyObject_IsTrue(o);Py_DECREF(o);
  const char* names[]={"before_inputs","before_outputs","after_inputs","after_outputs"};
  std::vector<int>* fields[]={&p->bi,&p->bo,&p->ai,&p->ao};
  for(int j=0;j<4;j++){o=attr(obj,names[j]);*fields[j]=ints(o);Py_DECREF(o);}
  if(p->width>128 || p->bo.size()>128 || p->ao.size()>128){delete p;Py_RETURN_NONE;}
  o=attr(obj,"tests");p->tests=pairs(o);Py_DECREF(o);
  o=attr(obj,"alternatives");
  for(Py_ssize_t j=0;j<PyTuple_GET_SIZE(o);j++)p->choices.push_back(pairs(PyTuple_GET_ITEM(o,j)));
  Py_DECREF(o);
  if(PyErr_Occurred()){delete p;return nullptr;}
  return PyCapsule_New(p,"wmcheck.port",destroy);
}
static PyObject* update(PyObject*,PyObject* args) {
  PyObject *capsule,*state;int choice;
  if(!PyArg_ParseTuple(args,"OOi",&capsule,&state,&choice))return nullptr;
  auto p=(Plan*)PyCapsule_GetPointer(capsule,"wmcheck.port");if(!p)return nullptr;
  if(choice<0 || size_t(choice)>=p->choices.size()){PyErr_SetString(PyExc_ValueError,"Invalid alternative");return nullptr;}
  Bits r[128]={},t[128]={};
  for(int i=0;i<p->width;i++)r[i]=Bits(1)<<i;
  for(int field=0;field<2;field++){
    auto rows=PyTuple_GET_ITEM(state,field);auto target=field?t:r;
    if(PyTuple_GET_SIZE(rows)!=0 && size_t(PyTuple_GET_SIZE(rows))!=p->bi.size()){
      PyErr_SetString(PyExc_ValueError,"Invalid state rows");return nullptr;
    }
    for(Py_ssize_t j=0;j<PyTuple_GET_SIZE(rows);j++){
      auto row=bits(PyTuple_GET_ITEM(rows,j));
      while(row){int b=first(row);row&=row-1;target[p->bi[j]]|=Bits(1)<<p->bo[b];}
    }
  }
  for(auto [u,v]:p->tests){
    if(r[v]&(Bits(1)<<u))Py_RETURN_NONE;
    for(int i=0;i<p->width;i++)if(r[i]&(Bits(1)<<u))t[i]|=r[v];
  }
  for(auto [u,v]:p->choices[choice]){
    if((p->acyclic?r[v]:t[v])&(Bits(1)<<u))Py_RETURN_NONE;
    if(r[u]&(Bits(1)<<v))continue;
    Bits successors=r[v],marked=t[v],bu=Bits(1)<<u;
    // Snapshot predecessor membership before any update.
    bool pre[128],markpre[128];
    for(int i=0;i<p->width;i++){pre[i]=r[i]&bu;markpre[i]=t[i]&bu;}
    for(int i=0;i<p->width;i++){
      if(!p->acyclic){if(markpre[i])t[i]|=successors;if(pre[i])t[i]|=marked;}
      if(pre[i])r[i]|=successors;
    }
  }
  std::vector<Bits> rr,tt;
  for(int i:p->ai){
    Bits a=0,b=0;
    for(size_t j=0;j<p->ao.size();j++){
      if(r[i]&(Bits(1)<<p->ao[j]))a|=Bits(1)<<j;
      if(t[i]&(Bits(1)<<p->ao[j]))b|=Bits(1)<<j;
    }
    rr.push_back(a);if(!p->acyclic)tt.push_back(b);
  }
  auto a=PyTuple_New(rr.size()),b=PyTuple_New(tt.size());
  for(size_t j=0;j<rr.size();j++)PyTuple_SET_ITEM(a,j,_PyLong_FromByteArray((const unsigned char*)&rr[j],16,1,0));
  for(size_t j=0;j<tt.size();j++)PyTuple_SET_ITEM(b,j,_PyLong_FromByteArray((const unsigned char*)&tt[j],16,1,0));
  return Py_BuildValue("NN",a,b);
}
static PyMethodDef methods[]={{"prepare",prepare,METH_O,nullptr},{"update",update,METH_VARARGS,nullptr},{nullptr,nullptr,0,nullptr}};
static PyModuleDef module={PyModuleDef_HEAD_INIT,"_port_native",nullptr,-1,methods};
PyMODINIT_FUNC PyInit__port_native(){return PyModule_Create(&module);}
