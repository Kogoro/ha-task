"""Device helpers for the Task integration."""

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import TaskCoordinator


def task_device_info(coordinator: TaskCoordinator, subentry_id: str) -> DeviceInfo:
    """Return the device info for a task or maintenance subentry.

    A device may only belong to one config entry, so a maintenance item never
    joins the device of the integration that owns the appliance. It gets its own
    device, linked to the appliance via ``via_device_id``.
    """
    entry_id = coordinator.config_entry.entry_id
    item = coordinator._find_item(subentry_id)
    task_name = item.name if item else "Task"
    if item and item.device_id:
        device = dr.async_get(coordinator.hass).async_get(item.device_id)
        return DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{subentry_id}")},
            name=(device.name_by_user or device.name) if device else task_name,
            suggested_area=coordinator.data.area_name,
            manufacturer="Task",
            model="Device Maintenance",
            **({"via_device_id": device.id} if device else {}),
        )
    entry_slug = coordinator.config_entry.title.lower().replace(" ", "_")
    task_slug = task_name.lower().replace(" ", "_")
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_slug}_{task_slug}")},
        name=task_name,
        suggested_area=coordinator.data.area_name,
        manufacturer="Task",
        model="Household Task",
    )
