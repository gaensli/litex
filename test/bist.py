import time
import argparse
from collections import OrderedDict
from config import *

KB = 1024
MB = 1024*KB
GB = 1024*MB

logical_sector_size = 512

class LiteSATABISTUnitDriver:
	def __init__(self, regs, name):
		self.regs = regs
		self.name = name
		self.frequency = regs.identifier_frequency.read()
		self.time = 0
		for s in ["start", "sector", "count", "random", "done", "errors", "cycles"]:
			setattr(self, s, getattr(regs, name + "_"+ s))

	def run(self, sector, count, random):
		self.sector.write(sector)
		self.count.write(count)
		self.random.write(random)
		self.start.write(1)
		while (self.done.read() == 0):
			pass
		self.time = self.cycles.read()/self.frequency
		speed = (count*logical_sector_size)/self.time
		errors = self.errors.read()
		return (speed, errors)

class LiteSATABISTGeneratorDriver(LiteSATABISTUnitDriver):
	def __init__(self, regs, name):
		LiteSATABISTUnitDriver.__init__(self, regs, name + "_generator")

class LiteSATABISTCheckerDriver(LiteSATABISTUnitDriver):
	def __init__(self, regs, name):
		LiteSATABISTUnitDriver.__init__(self, regs, name + "_checker")

class LiteSATABISTIdentifyDriver:
	def __init__(self, regs, name):
		self.regs = regs
		self.name = name
		for s in ["start", "done", "source_stb", "source_ack", "source_data"]:
			setattr(self, s, getattr(regs, name + "_identify_"+ s))
		self.data = []

	def read_fifo(self):
		self.data = []
		while self.source_stb.read():
			dword = self.source_data.read()
			word_lsb = dword & 0xffff
			word_msb = (dword >> 16) & 0xffff
			self.data += [word_lsb, word_msb]
			self.source_ack.write(1)

	def run(self):
		self.read_fifo() # flush the fifo before we start
		self.start.write(1)
		while (self.done.read() == 0):
			pass
		self.read_fifo()
		self.decode()

	def decode(self):
		self.serial_number = ""
		for i, word in enumerate(self.data[10:20]):
			s = word.to_bytes(2, byteorder='big').decode("utf-8")
			self.serial_number += s
		self.firmware_revision = ""
		for i, word in enumerate(self.data[23:27]):
			s = word.to_bytes(2, byteorder='big').decode("utf-8")
			self.firmware_revision += s
		self.model_number = ""
		for i, word in enumerate(self.data[27:46]):
			s = word.to_bytes(2, byteorder='big').decode("utf-8")
			self.model_number += s

		self.total_sectors = self.data[100]
		self.total_sectors += (self.data[101] << 16)
		self.total_sectors += (self.data[102] << 32)
		self.total_sectors += (self.data[103] << 48)

		self.capabilities = OrderedDict()
		self.capabilities["SATA Gen1"] = (self.data[76] >> 1) & 0x1
		self.capabilities["SATA Gen2"] = (self.data[76] >> 2) & 0x1
		self.capabilities["SATA Gen3"] = (self.data[76] >> 3) & 0x1
		self.capabilities["48 bits LBA supported"] = (self.data[83] >> 10) & 0x1

	def hdd_info(self):
		info = "Serial Number: " + self.serial_number + "\n"
		info += "Firmware Revision: " + self.firmware_revision + "\n"
		info += "Model Number: " + self.model_number + "\n"
		info += "Capacity: %3.2f GB\n" %((self.total_sectors*logical_sector_size)/GB)
		for k, v in self.capabilities.items():
			info += k + ": " + str(v) + "\n"
		print(info)

def _get_args():
	parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
		description="""\
SATA BIST utility.
""")
	parser.add_argument("-s", "--transfer_size", default=4, help="transfer sizes (in MB, up to 16MB)")
	parser.add_argument("-l", "--total_length", default=256, help="total transfer length (in MB, up to HDD capacity)")
	parser.add_argument("-r", "--random", action="store_true", help="use random data")
	parser.add_argument("-c", "--continuous", action="store_true", help="continuous mode (Escape to exit)")
	parser.add_argument("-i", "--identify", action="store_true", help="only run identify")
	return parser.parse_args()

if __name__ == "__main__":
	args = _get_args()
	wb.open()
	###
	identify = LiteSATABISTIdentifyDriver(wb.regs, "sata_bist")
	generator = LiteSATABISTGeneratorDriver(wb.regs, "sata_bist")
	checker = LiteSATABISTCheckerDriver(wb.regs, "sata_bist")

	identify.run()
	identify.hdd_info()

	if not int(args.identify):
		sector = 0
		count = int(args.transfer_size)*MB//logical_sector_size
		length = int(args.total_length)*MB
		random = int(args.random)
		continuous = int(args.continuous)
		try:
			while ((sector*logical_sector_size < length) or continuous) and (sector < identify.total_sectors):
				# generator (write data to HDD)
				write_speed, write_errors = generator.run(sector, count, random)

				# checker (read and check data from HDD)
				read_speed, read_errors = checker.run(sector, count, random)

				print("sector=%d write_speed=%4.2fMB/sec read_speed=%4.2fMB/sec errors=%d" %(sector, write_speed/MB, read_speed/MB, write_errors + read_errors))
				sector += count

		except KeyboardInterrupt:
			pass
	###
	wb.close()
