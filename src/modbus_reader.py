"""
KWB logger – Modbus TCP reader
Compatible with pymodbus 3.13+ (device_id keyword, count keyword-only)
"""

import logging
import struct
from dataclasses import dataclass
from typing import Optional

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from registers import Register

logger = logging.getLogger(__name__)


@dataclass
class ReadResult:
    register    : Register
    raw_value   : Optional[int]
    scaled_value: Optional[float]
    error       : Optional[str] = None


def _to_int16(raw: int) -> int:
    return struct.unpack(">h", struct.pack(">H", raw & 0xFFFF))[0]


def _to_int32(hi: int, lo: int) -> int:
    return struct.unpack(">i", struct.pack(">HH", hi & 0xFFFF, lo & 0xFFFF))[0]


def _to_uint32(hi: int, lo: int) -> int:
    return (hi << 16) | lo


def connect(host: str, port: int, timeout: int) -> ModbusTcpClient:
    client = ModbusTcpClient(host=host, port=port, timeout=timeout)
    if not client.connect():
        raise ConnectionError(f"Cannot connect to {host}:{port}")
    logger.info(f"Connected to KWB at {host}:{port}")
    return client


def _read(client, fc, address, count, device_id):
    try:
        if fc == 4:
            resp = client.read_input_registers(address, count=count, device_id=device_id)
        else:
            resp = client.read_holding_registers(address, count=count, device_id=device_id)
        if resp.isError():
            return None, str(resp)
        return resp.registers, None
    except ModbusException as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def read_registers(client, registers: list[Register], device_id: int) -> list[ReadResult]:
    results = []
    for reg in registers:
        is_32 = reg.dtype in ("u32", "s32")
        count = 2 if is_32 else 1
        regs, err = _read(client, reg.fc, reg.address, count, device_id)

        if regs is None:
            results.append(ReadResult(reg, None, None, err))
            continue

        try:
            if reg.dtype == "u32":
                raw = _to_uint32(regs[0], regs[1])
            elif reg.dtype == "s32":
                raw = _to_int32(regs[0], regs[1])
            elif reg.dtype == "s16":
                raw = _to_int16(regs[0])
            else:  # u16
                raw = regs[0]

            results.append(ReadResult(reg, raw, raw * reg.scale))

        except Exception as e:
            results.append(ReadResult(reg, None, None, str(e)))

    return results
