"""
Component registry for PerfBoardMaker.
"""
from typing import Optional
from app.models.component_def import ComponentDef
from app.components.arduino_nano import ArduinoNanoDef
from app.components.push_button import PushButtonDef
from app.components.capacitor import ElectrolyticCapacitorDef
from app.components.to220 import TO220Def
from app.components.to92 import TO92Def
from app.components.nrf24l01 import NRF24L01Def
from app.components.nrf24l01_pa_lna import NRF24L01PALNADef
from app.components.passives import (
    ResistorDef, CeramicCapacitorDef, DiodeAxialDef, LEDDef, CrystalDef, BuzzerDef
)
from app.components.switches_pots import (
    TrimmerPotDef, RotaryPot16mmDef, SlideSwitchSPDTDef, TactileButton12x12Def
)
from app.components.dip_ic import DIPPackageDef
from app.components.connectors import (
    PinHeader1xDef, PinHeader2xDef, ScrewTerminalDef, DCBarrelJackDef, JSTXHDef
)
from app.components.esp_boards import (
    WemosD1MiniDef, NodeMCUv2Def, NodeMCUv3Def, ESP01Def,
    ESP32DevKit30Def, ESP32DevKit38Def, ESP32SuperMiniDef
)
from app.components.modules import (
    MX1508Def, L298NDef, Mini360Def, LM2596Def,
    RelayModule5VDef, SRD05VDCRelayDef, OLED096I2CDef
)


class ComponentRegistry:
    def __init__(self):
        self._components: dict[str, ComponentDef] = {}
        self._categories: list[str] = [
            "Microcontrollers",
            "Passives & Switches",
            "Connectors & Headers",
            "Semiconductors & ICs",
            "Power & Motor Drivers",
            "Wireless & RF",
        ]
        self._register_builtins()

    def _register_builtins(self):
        # 1. Microcontrollers
        self.register(ArduinoNanoDef())
        self.register(WemosD1MiniDef())
        self.register(NodeMCUv2Def())
        self.register(NodeMCUv3Def())
        self.register(ESP32DevKit30Def())
        self.register(ESP32DevKit38Def())
        self.register(ESP32SuperMiniDef("C3"))
        self.register(ESP32SuperMiniDef("C6"))

        # 2. Passives & Switches
        self.register(ResistorDef())
        self.register(CeramicCapacitorDef())
        self.register(ElectrolyticCapacitorDef("5mm"))
        self.register(ElectrolyticCapacitorDef("8mm"))
        self.register(ElectrolyticCapacitorDef("10mm"))
        self.register(DiodeAxialDef())
        self.register(LEDDef("3mm"))
        self.register(LEDDef("5mm"))
        self.register(CrystalDef())
        self.register(BuzzerDef())
        self.register(TrimmerPotDef())
        self.register(RotaryPot16mmDef())
        self.register(SlideSwitchSPDTDef())
        self.register(PushButtonDef())
        self.register(TactileButton12x12Def())

        # 3. Connectors & Headers
        self.register(PinHeader1xDef())
        self.register(PinHeader2xDef())
        self.register(ScrewTerminalDef(1))  # 2.54mm
        self.register(ScrewTerminalDef(2))  # 5.08mm
        self.register(DCBarrelJackDef())
        self.register(JSTXHDef(2))
        self.register(JSTXHDef(3))

        # 4. Semiconductors & ICs
        self.register(DIPPackageDef(8))
        self.register(DIPPackageDef(14))
        self.register(DIPPackageDef(16))
        self.register(DIPPackageDef(28))
        self.register(TO220Def())
        self.register(TO92Def())

        # 5. Power & Motor Drivers
        self.register(MX1508Def())
        self.register(L298NDef())
        self.register(Mini360Def())
        self.register(LM2596Def())
        self.register(RelayModule5VDef(1))
        self.register(RelayModule5VDef(2))
        self.register(SRD05VDCRelayDef())
        self.register(OLED096I2CDef())

        # 6. Wireless & RF
        self.register(ESP01Def())
        self.register(NRF24L01Def())
        self.register(NRF24L01PALNADef())

    def register(self, comp_def: ComponentDef):
        self._components[comp_def.type_id] = comp_def
        if comp_def.category not in self._categories:
            self._categories.append(comp_def.category)

    def get(self, type_id: str) -> Optional[ComponentDef]:
        return self._components.get(type_id)

    def get_all(self) -> list[ComponentDef]:
        return list(self._components.values())

    def get_categories(self) -> list[str]:
        return self._categories

    def get_by_category(self, category: str) -> list[ComponentDef]:
        return [c for c in self._components.values() if c.category == category]

# Global singleton
REGISTRY = ComponentRegistry()
