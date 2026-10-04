#!/usr/bin/env python3

import sys
import socket
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} INTERFACE HOSTNAME", file=sys.stderr)
    sys.exit(2)

interface_name = sys.argv[1]
hostname = sys.argv[2]

ifindex = socket.if_nametoindex(interface_name)

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

server_obj = bus.get_object("org.freedesktop.Avahi", "/")
server = dbus.Interface(
    server_obj,
    "org.freedesktop.Avahi.Server"
)

# protocol:
#   -1 = unspecified
# address protocol:
#    0 = IPv4
resolver_path = server.HostNameResolverNew(
    dbus.Int32(ifindex),
    dbus.Int32(-1),
    hostname,
    dbus.Int32(0),
    dbus.UInt32(0)
)

resolver_obj = bus.get_object(
    "org.freedesktop.Avahi",
    resolver_path
)

resolver = dbus.Interface(
    resolver_obj,
    "org.freedesktop.Avahi.HostNameResolver"
)

loop = GLib.MainLoop()
result = {"address": None}

def on_found(interface, protocol, name, aprotocol, address, flags):
    result["address"] = str(address)
    print(address)
    loop.quit()

def on_failure(error):
    print(f"Avahi resolve failed: {error}", file=sys.stderr)
    loop.quit()

def on_timeout():
    print("Avahi resolve timed out.", file=sys.stderr)
    loop.quit()
    return False

resolver.connect_to_signal("Found", on_found)
resolver.connect_to_signal("Failure", on_failure)

GLib.timeout_add_seconds(3, on_timeout)

loop.run()

if result["address"] is None:
    sys.exit(1)