"""Known Navitaire help families and the signals used to recognise them.

Patterns are case-insensitive regular expressions. They are matched against:

* ``filename``      - the CHM file name
* ``title``         - the compiled title (#SYSTEM), the welcome-page title and the contents-file name
* ``path``          - the installation folder path relative to the discovery root
* ``executables``   - executable file names whose version resource identifies the installed product
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Family:
    family_id: str
    product: str
    domain: str
    filename: tuple[str, ...] = ()
    title: tuple[str, ...] = ()
    path: tuple[str, ...] = ()
    executables: tuple[str, ...] = field(default_factory=tuple)


FAMILIES: tuple[Family, ...] = (
    Family(
        "gonow", "GoNow", "Airport check-in, boarding, baggage and departure control",
        filename=(r"^gonow",), title=(r"\bgo\s?now\b",), path=(r"(^|\\)gonow(\\|$)",),
        executables=("gonow.exe",),
    ),
    Family(
        "skyspeed", "SkySpeed Reservation Manager", "Reservations, sales and passenger servicing",
        filename=(r"^skyspeed",), title=(r"\bskyspeed\b",), path=(r"skyspeed",),
        executables=("ui.win.skyspeed.exe",),
    ),
    Family(
        "skyfare", "Fare Manager", "Fares, fare rules, markets and pricing",
        filename=(r"^skyfare",), title=(r"\bfare manager\b", r"\bskyfare\b"), path=(r"(^|\\)fare manager(\\|$)",),
        executables=("ui.win.skyfare.exe",),
    ),
    Family(
        "skyschedule", "Schedule Manager", "Flight schedules, legs, routes and equipment",
        filename=(r"^skyschedule",), title=(r"\bschedule manager\b", r"\bskyschedule\b"),
        path=(r"(^|\\)schedule manager(\\|$)",),
        executables=("ui.win.skyschedule.exe",),
    ),
    Family(
        "newskies-management-console", "New Skies Management Console",
        "System configuration, roles, permissions and reference data",
        filename=(r"skymanagerhelp",), title=(r"\bskymanager\b", r"new skies management console"),
        path=(r"client suite\\management console",),
    ),
    Family(
        "gss-management-console", "GSS Management Console",
        "Government Security Services: APIS/APPS, rules and government messaging",
        filename=(r"gssmanagementconsole", r"governmentsecurity"),
        title=(r"government\s*security", r"\bgss\b"), path=(r"(^|\\)governmentsecurity(\\|$)",),
        executables=("governmentsecurity.managementconsole.exe",),
    ),
    Family(
        "device-manager", "Device Manager", "Peripheral devices, scanners, printers, simulators and logs",
        filename=(r"^devicemanager",), title=(r"\bdevice manager\b",), path=(r"(^|\\)devicemanager(\\|$)",),
        executables=("devicemanager.exe",),
    ),
    Family(
        "ncs-rules", "Rules Management", "Management Console rules plug-in",
        filename=(r"^rules\.chm$",), title=(r"\brules?\b",), path=(r"ncs\.rules",),
    ),
    Family(
        "ncs-currency", "Currency Management", "Management Console currency plug-in",
        filename=(r"^currency\.chm$",), title=(r"\bcurrenc(y|ies)\b",), path=(r"ncs\.currency",),
    ),
    Family(
        "ncs-notification", "Notification Management", "Management Console notification plug-in",
        filename=(r"^notification\.chm$",), title=(r"\bnotifications?\b",), path=(r"ncs\.notification",),
    ),
)

UNKNOWN = Family("unknown", "Unknown", "CHM not recognised as a Navitaire help family")

BY_ID = {f.family_id: f for f in FAMILIES}


def get(family_id: str) -> Family:
    return BY_ID.get(family_id, UNKNOWN)
