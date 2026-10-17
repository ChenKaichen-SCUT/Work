// Adapter for Dat3M b81ec6c55503e824bb0ddc4ebac6c6f0a63d56d8.
// Runs the original NativeRelationAnalysis; does not reimplement its rules.
import com.dat3m.dartagnan.configuration.Arch;
import com.dat3m.dartagnan.configuration.Property;
import com.dat3m.dartagnan.parsers.cat.ParserCat;
import com.dat3m.dartagnan.parsers.program.ProgramParser;
import com.dat3m.dartagnan.program.Program;
import com.dat3m.dartagnan.program.analysis.EventDomainRepository;
import com.dat3m.dartagnan.program.event.Event;
import com.dat3m.dartagnan.program.event.core.*;
import com.dat3m.dartagnan.verification.*;
import com.dat3m.dartagnan.wmm.*;
import com.dat3m.dartagnan.wmm.analysis.RelationAnalysis;
import com.dat3m.dartagnan.wmm.utils.graph.mutable.MapEventGraph;
import com.dat3m.dartagnan.wmm.utils.graph.mutable.IndexedEventGraph;
import org.sosy_lab.common.configuration.Configuration;
import java.nio.file.*;
import java.util.*;
import static com.dat3m.dartagnan.configuration.OptionNames.*;
import static com.dat3m.dartagnan.verification.solving.ModelChecker.*;

public class Dat3mSupportAudit {
  public static void main(String[] args) throws Exception {
    Program program = new ProgramParser().parse(Path.of(args[0]));
    Wmm wmm = new ParserCat().parse(Path.of(args[1]));
    Configuration config = Configuration.builder().setOption(RELATION_ANALYSIS,"NATIVE")
        .setOption(ENABLE_EXTENDED_RELATION_ANALYSIS,"true").build();
    Task task = Task.builder().withConfig(config).withBound(2).withTarget(Arch.C11)
        .build(program,wmm,EnumSet.of(Property.PROGRAM_SPEC));
    preprocessProgram(task,task.getConfig());
    preprocessMemoryModel(task);
    Map<String,Event> events = new LinkedHashMap<>();
    Map<String,Event> nativeIds = new HashMap<>();
    for (var thread: program.getThreads()) {
      int index=0;
      for (Event e:thread.getEvents()) {
        if(e instanceof Init i) nativeIds.put("init:"+i.getBase().getName(),e);
        else if(e instanceof Load || e instanceof Store) nativeIds.put(thread.getId()+":"+(index++),e);
      }
    }
    if(args.length==2) {
      for(var e:nativeIds.entrySet()) System.out.println(e.getKey()+"\t"+e.getValue());
      return;
    }
    for(String line:Files.readAllLines(Path.of(args[2]))) {
      String[] p=line.split("\\t");
      Event e=Objects.requireNonNull(nativeIds.get(p[1]),"Missing "+p[1]);
      if((p[2].equals("R")) != (e instanceof Load)) throw new IllegalArgumentException("Kind "+line);
      if(!((MemoryCoreEvent)e).getAddress().toString().equals(p[3]))
        throw new IllegalArgumentException("Address "+line+" native="+((MemoryCoreEvent)e).getAddress());
      events.put(p[0],e);
    }
    if(events.size()!=nativeIds.size()) throw new IllegalArgumentException("Event count mismatch");
    Map<String,MapEventGraph> may=new HashMap<>(),must=new HashMap<>();
    for(String line:Files.readAllLines(Path.of(args[3]))) {
      String[] p=line.split("\\t");
      var table=p[1].equals("may")?may:must;
      table.computeIfAbsent(p[0],x->new MapEventGraph()).add(events.get(p[2]),events.get(p[3]));
    }
    Context context=Context.create();
    performStaticProgramAnalyses(task,context,task.getConfig());
    var domain=context.get(EventDomainRepository.class).getDomain(EventDomainRepository.DomainBound.ALL);
    for(String rel:List.of("rf","co","hb")) {
      MapEventGraph all=may.get(rel);
      if(all==null) {
        all=new MapEventGraph();
        for(var t:program.getThreads()) for(Event a:t.getEvents())
          for(var u:program.getThreads()) for(Event b:u.getEvents()) all.add(a,b);
      }
      wmm.addConstraint(new Assumption(wmm.getRelation(rel),all,
          new IndexedEventGraph(domain,domain,must.getOrDefault(rel,new MapEventGraph()))));
    }
    performStaticWmmAnalyses(task,context,task.getConfig());
    RelationAnalysis analysis=context.get(RelationAnalysis.class);
    List<String> output=new ArrayList<>();
    for(String rel:List.of("rf","co","hb")) {
      var k=analysis.getKnowledge(wmm.getRelation(rel));
      for(var a:events.entrySet()) for(var b:events.entrySet()) {
        if(k.getMaySet().contains(a.getValue(),b.getValue())) output.add(rel+"\tmay\t"+a.getKey()+"\t"+b.getKey());
        if(k.getMustSet().contains(a.getValue(),b.getValue())) output.add(rel+"\tmust\t"+a.getKey()+"\t"+b.getKey());
      }
    }
    Files.write(Path.of(args[4]),output);
    System.out.println("AUDIT events="+events.size()+" contradictions="+analysis.getContradictions().size()+" output="+output.size());
  }
}
