// Ghidra headless script: trace media-related string xrefs and decompile referencing functions.
//
// Usage (headless):
//   analyzeHeadless <projDir> <projName> -process libArLink.so \
//     -postScript /path/to/GhidraTraceMediaNative.java /tmp/libArLink_media_trace.txt

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;

public class GhidraTraceMediaNative extends GhidraScript {

	private static final String[] TARGETS = {
		"OnPBVideo_RecvData",
		"OnPBAudio_RecvData",
		"OnPBEnd",
		"OnFileDownload_RecvData",
		"Media file check failed",
		"File download data, dirNum",
		"Start play cmd, seq",
		"Stop play cmd",
		"lwlaes_decrypt"
	};

	private static class StrHit {
		String needle;
		Address addr;
		String text;
		StrHit(String needle, Address addr, String text) {
			this.needle = needle;
			this.addr = addr;
			this.text = text;
		}
	}

	@Override
	protected void run() throws Exception {
		String outPath = "/tmp/libArLink_media_trace.txt";
		String[] args = getScriptArgs();
		if (args != null && args.length > 0 && args[0] != null && !args[0].isBlank()) {
			outPath = args[0];
		}

		List<StrHit> hits = findStringHits();
		Map<Address, Function> uniqFuncs = new LinkedHashMap<>();
		StringBuilder sb = new StringBuilder();
		sb.append("Program: ").append(currentProgram.getName()).append('\n').append('\n');

		for (StrHit h : hits) {
			sb.append("=== STRING MATCH ===\n");
			sb.append("needle: ").append(h.needle).append('\n');
			sb.append("addr: ").append(h.addr).append('\n');
			sb.append("text: ").append(h.text).append('\n');

			List<Function> fns = functionsReferencing(h.addr);
			if (fns.isEmpty()) {
				sb.append("xrefs: none\n\n");
				continue;
			}
			sb.append("xrefs functions:\n");
			for (Function f : fns) {
				sb.append("  - ").append(f.getName()).append(" @ ").append(f.getEntryPoint()).append('\n');
				uniqFuncs.put(f.getEntryPoint(), f);
			}
			sb.append('\n');
		}

		sb.append("=== UNIQUE REFERENCING FUNCTIONS (DECOMPILED) ===\n");
		DecompInterface ifc = new DecompInterface();
		ifc.openProgram(currentProgram);
		for (Function f : uniqFuncs.values()) {
			sb.append('\n');
			sb.append("--- ").append(f.getName()).append(" @ ").append(f.getEntryPoint()).append(" ---\n");
			sb.append(decompile(ifc, f)).append('\n');
		}
		ifc.dispose();

		writeFile(outPath, sb.toString());
		println("Wrote " + outPath);
	}

	private List<StrHit> findStringHits() {
		List<StrHit> out = new ArrayList<>();
		Listing listing = currentProgram.getListing();
		DataIterator it = listing.getDefinedData(true);
		while (it.hasNext() && !monitor.isCancelled()) {
			Data d = it.next();
			Object v = d.getValue();
			if (!(v instanceof String)) {
				continue;
			}
			String s = (String) v;
			for (String needle : TARGETS) {
				if (s.contains(needle)) {
					out.add(new StrHit(needle, d.getAddress(), s));
					break;
				}
			}
		}
		return out;
	}

	private List<Function> functionsReferencing(Address addr) {
		Map<Address, Function> uniq = new LinkedHashMap<>();
		ReferenceManager rm = currentProgram.getReferenceManager();
		FunctionManager fm = currentProgram.getFunctionManager();
		ReferenceIterator refs = rm.getReferencesTo(addr);
		while (refs.hasNext()) {
			Reference r = refs.next();
			Function f = fm.getFunctionContaining(r.getFromAddress());
			if (f != null) {
				uniq.put(f.getEntryPoint(), f);
			}
		}
		return new ArrayList<>(uniq.values());
	}

	private String decompile(DecompInterface ifc, Function f) {
		try {
			DecompileResults res = ifc.decompileFunction(f, 60, monitor);
			if (!res.decompileCompleted() || res.getDecompiledFunction() == null) {
				return "/* decompile failed for " + f.getName() + " */";
			}
			return res.getDecompiledFunction().getC();
		} catch (Exception e) {
			return "/* exception decompiling " + f.getName() + ": " + e + " */";
		}
	}

	private void writeFile(String path, String text) throws IOException {
		Files.write(Paths.get(path), text.getBytes(StandardCharsets.UTF_8));
	}
}

