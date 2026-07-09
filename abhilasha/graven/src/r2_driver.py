from pathlib import Path
import r2pipe
import pyghidra
import re

DANGEROUS = {"strcpy", "strcat", "sprintf", "gets", "scanf", "memcpy"}

class R2Driver:
	def __init__(self, binary_path):
		self.path_to_binary = binary_path
		self.r2session = None
	def open(self):
		self.r2session = r2pipe.open(self.path_to_binary, flags=["-2"])
		self.r2session.cmd("aaa")
		pyghidra.start()
		from ghidra.program.model.data import StringDataInstance
		self.StringDataInstance = StringDataInstance
		self.ghidra_context = pyghidra.open_program(self.path_to_binary)
		self.flat_api = self.ghidra_context.__enter__()
		program = self.flat_api.getCurrentProgram()
		from ghidra.app.decompiler import DecompInterface
		self.decomp = DecompInterface()
		self.decomp.openProgram(program)
		self.program = program
	def close(self):
		if self.r2session:
			self.r2session.quit()
		if hasattr(self, "ghidra_context"):
			self.ghidra_context.__exit__(None, None, None)
	def get_functions(self):
		return self.r2session.cmdj("aflj")
	def get_user_functions(self):
		func_list = self.get_functions()
		filtered_list = []
		for f in func_list:
			if "file" in f and not f["name"].startswith("entry"):
				filtered_list.append(f)
		return filtered_list
	def get_dangerous_imports(self):
		imp_list = self.r2session.cmdj("iij")
		dang_imp = []
		for i in imp_list:
			if i["name"] in DANGEROUS:
				dang_imp.append(i["name"])
		return dang_imp
	def get_decompiled(self, func):
		clean_name = func.replace("dbg.", "").replace("sym.", "")
		func_manager = self.program.getFunctionManager()
		for func in func_manager.getFunctions(True):
			if func.getName() == clean_name:
				result = self.decomp.decompileFunction(func, 60, None)
				code = result.getDecompiledFunction().getC()
				return self.resolve_strings(code)
		return ""
	def get_string_at(self, addr_str):
		addr = self.program.getAddressFactory() \
			.getDefaultAddressSpace() \
			.getAddress(addr_str)
		mem = self.program.getMemory()
		chars = []
		while True:
			b = mem.getByte(addr) & 0xff
			if b == 0:
				break
			chars.append(chr(b))
			addr = addr.next()
		return "".join(chars)
	def resolve_strings(self, code):
		def replace(match):
			addr = match.group(1)
			try:
				s = self.get_string_at(addr)
				if s:
					return '"' + s + '"'
			except:
				pass
			return match.group(0)
		return re.sub(r"&?DAT_([0-9A-Fa-f]{8})", replace, code)


if __name__ == "__main__":
	d = R2Driver(str(Path("corpus/bin/safe04_scanfw")))
	d.open()
	func = d.get_user_functions()
	#for f in func:
	#	print(f["name"])
	#print(d.get_dangerous_imports())
	print(d.get_decompiled("dbg.rd"))
	print(d.get_decompiled("dbg.main"))
	#print(d.get_string_at("00402004"))
	d.close()
