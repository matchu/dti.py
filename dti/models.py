import asyncio
from os import PathLike
from typing import Dict, List, Optional, Union, BinaryIO

from .constants import (
    CLOSEST_POSES_IN_ORDER,
    GRAB_PET_APPEARANCES_BY_IDS,
    PET_ON_NEOPETS,
    GRAB_PET_APPEARANCES_BY_NAMES,
)
from .decorators import _require_state
from .enums import PetPose, LayerImageSize
from .errors import (
    MissingPetAppearance,
    InvalidColorSpeciesPair,
    NeopetNotFound,
    BrokenAssetImage,
)
from .mixins import Object
from .state import State


class Species(Object):
    __slots__ = ("_state", "id", "name")

    def __init__(self, *, state: State, data: Dict):
        self._state = state
        self.id = int(data["id"])
        self.name = data["name"]

    @_require_state
    async def _color_iterator(self, valid: bool = True) -> List["Color"]:
        found = []
        for color_id in range(1, self._state._valid_pairs.color_count + 1):
            is_valid = self._state._valid_pairs.check(
                species_id=self.id, color_id=color_id
            )
            if is_valid == valid:
                found.append(self._state._colors[color_id])
        return found

    async def colors(self) -> List["Color"]:
        return await self._color_iterator()

    async def missing_colors(self) -> List["Color"]:
        return await self._color_iterator(valid=False)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<Species id={self.id} name={self.name!r}>"


class Color(Object):
    __slots__ = ("_state", "id", "name")

    def __init__(self, *, state: State, data: Dict):
        self._state = state
        self.id = int(data["id"])
        self.name = data["name"]

    @_require_state
    async def _species_iterator(self, valid: bool = True) -> List["Species"]:
        found = []
        for species_id in range(1, self._state._valid_pairs.species_count + 1):
            is_valid = self._state._valid_pairs.check(
                species_id=species_id, color_id=self.id
            )
            if is_valid == valid:
                found.append(self._state._species[species_id])
        return found

    async def species(self) -> List["Species"]:
        return await self._species_iterator()

    async def missing_species(self) -> List["Species"]:
        return await self._species_iterator(valid=False)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<Color id={self.id} name={self.name!r}>"


class Zone(Object):
    __slots__ = ("id", "depth", "label")

    def __init__(self, data: Dict):
        self.id = int(data["id"])
        self.depth = int(data["depth"])
        self.label = data["label"]

    def __repr__(self):
        return f"<Zone id={self.id} label={self.label!r} depth={self.depth}>"


class AppearanceLayer(Object):
    __slots__ = ("id", "zone", "image_url", "asset_type", "asset_remote_id")

    def __init__(self, **data):
        self.id = data["id"]
        self.image_url = data["imageUrl"]
        self.asset_remote_id = data["remoteId"]
        self.zone = Zone(data["zone"])
        self.asset_type = data["asset_type"]

    def __repr__(self):
        return f"<AppearanceLayer zone={self.zone!r} url={self.image_url!r} asset_type={self.asset_type!r}>"


class PetAppearance(Object):
    __slots__ = (
        "id",
        "body_id",
        "species",
        "color",
        "pose",
        "layers",
        "restricted_zones",
    )

    def __init__(self, *, state: State, data: Dict):
        self.id = data["id"]
        self.body_id = data["bodyId"]

        # create new, somewhat temporary colors from this data since we don't have async access
        self.color = Color(data=data["color"], state=state)
        self.species = Species(data=data["species"], state=state)

        self.pose = PetPose(data["pose"])
        self.layers = [
            AppearanceLayer(**layer, asset_type="biology") for layer in data["layers"]
        ]
        self.restricted_zones = [
            Zone(restricted) for restricted in data["restrictedZones"]
        ]

    def __repr__(self):
        return f"<PetAppearance species={self.species!r} color={self.color!r} pose={self.pose!r}>"


class ItemAppearance(Object):
    __slots__ = ("id", "layers", "restricted_zones")

    def __init__(self, data: Dict):
        self.id = data["id"]
        self.layers = [
            AppearanceLayer(**layer, asset_type="object") for layer in data["layers"]
        ]
        self.restricted_zones = [
            Zone(restricted) for restricted in data["restrictedZones"]
        ]

    @property
    def occupies(self) -> List[Zone]:
        """A convenience property to return the zones of each layer for the item appearance."""
        return [layer.zone for layer in self.layers]


class Item(Object):
    __slots__ = (
        "id",
        "name",
        "description",
        "thumbnail_url",
        "appearance",
        "is_nc",
        "is_pb",
        "rarity",
    )

    def __init__(self, **data):
        self.id = int(data["id"])
        self.name = data.get("name")
        self.description = data.get("description")
        self.thumbnail_url = data.get("thumbnailUrl")
        self.is_nc = data.get("isNc")
        self.is_pb = data.get("isPb")
        self.rarity = data.get("rarityIndex")

        appearance_data = data.get("appearanceOn", None)
        self.appearance = appearance_data and ItemAppearance(appearance_data)

    @property
    def url(self) -> str:
        return (
            f'http://impress.openneo.net/items/{self.id}-{self.name.replace(" ", "-")}'
        )

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<Item id={self.id} name={self.name!r} is_nc={self.is_nc} is_pb={self.is_pb} rarity={self.rarity}>"


class Neopet:
    __slots__ = (
        "_valid_poses",
        "state",
        "species",
        "color",
        "appearances",
        "items",
        "name",
        "pose",
        "size",
    )

    def __init__(
        self,
        *,
        species: Species,
        color: Color,
        valid_poses: int,
        pose: PetPose,
        appearances: List[PetAppearance],
        items: Optional[List[Item]] = None,
        size: Optional[LayerImageSize] = None,
        name: Optional[str] = None,
        state: State,
    ):
        self.state = state
        self.species = species
        self.color = color
        self.appearances = appearances
        self.items = items or []
        self.name = name
        self.size = size
        self.pose = pose
        self._valid_poses = valid_poses

    @classmethod
    async def fetch_assets_for(
        cls,
        *,
        species: Species,
        color: Color,
        pose: PetPose,
        item_ids: Optional[List[Union[str, int]]] = None,
        item_names: Optional[List[str]] = None,
        size: Optional[LayerImageSize] = None,
        name: Optional[str] = None,
        state: State,
    ) -> "Neopet":
        """Returns the data for a species+color+pose combo, optionally with items, an image size, and a name for internal usage."""

        if not await state._check(species_id=species.id, color_id=color.id):
            raise InvalidColorSpeciesPair(
                f"The {species} species does not have the color {color}"
            )

        # note: sizes are not editable once the Neopet object is made
        size = size or LayerImageSize.SIZE_600

        variables = {
            "speciesId": species.id,
            "colorId": color.id,
            "size": str(size),
        }

        if item_names:
            variables["names"] = item_names or []
            query = GRAB_PET_APPEARANCES_BY_NAMES
            key = "itemsByName"
        else:
            variables["allItemIds"] = item_ids or []
            query = GRAB_PET_APPEARANCES_BY_IDS
            key = "items"

        data = await state.http.query(query=query, variables=variables)

        error = data.get("error")
        if error:
            if "it is undefined" in error["message"]:
                raise InvalidColorSpeciesPair(
                    f"The {species} species does not have the color {color}"
                )

        data = data["data"]
        items = [Item(**item) for item in data[key] if item is not None]
        appearances = [
            PetAppearance(data=appearance, state=state)
            for appearance in data["petAppearances"]
        ]

        bit = await state._get_bit(species_id=species.id, color_id=color.id)

        return Neopet(
            species=species,
            color=color,
            pose=pose,
            valid_poses=bit,
            items=items,
            appearances=appearances,
            name=name,
            size=size,
            state=state,
        )

    @classmethod
    async def fetch_by_name(
        cls, *, state: State, pet_name: str, size: Optional[LayerImageSize] = None
    ) -> "Neopet":
        """Returns the data for a specific neopet, by name."""
        data = await state.http.query(
            query=PET_ON_NEOPETS, variables={"petName": pet_name}
        )

        error = data.get("errors")
        if error:
            raise NeopetNotFound(error[0]["message"])

        data = data["data"]["petOnNeopetsDotCom"]

        neopet = await Neopet.fetch_assets_for(
            species=await state._get_species(data["species"]["id"]),
            color=await state._get_color(data["color"]["id"]),
            item_ids=[item["id"] for item in data["items"]],
            pose=PetPose(data["pose"]),
            size=size,
            name=pet_name,
            state=state,
        )
        return neopet

    @property
    def legacy_closet_url(self) -> str:
        """Returns the legacy closet URL for a neopet customization."""
        from urllib.parse import urlencode
        from collections import OrderedDict

        params = OrderedDict()
        if self.name:
            params["name"] = self.name

        params["species"] = self.species.id
        params["color"] = self.color.id

        valid_poses = self.valid_poses()
        if len(valid_poses):
            appearance = self.get_pet_appearance(valid_poses[0])
            if appearance:
                params["state"] = appearance.id

        if self.items:
            params["objects[]"] = [item.id for item in self.items]
            params["closet[]"] = [item.id for item in self.items]

        return "https://impress.openneo.net/wardrobe#" + urlencode(params, doseq=True)

    @property
    def closet_url(self) -> str:
        """Returns the closet URL for a neopet customization."""
        from urllib.parse import urlencode
        from collections import OrderedDict

        params = OrderedDict()
        if self.name:
            params["name"] = self.name

        params["species"] = self.species.id
        params["color"] = self.color.id

        valid_poses = self.valid_poses()
        if len(valid_poses):
            params["pose"] = valid_poses[0]

        if self.items:
            params["objects[]"] = [item.id for item in self.items]

        return self.state.http.BASE + "/outfits/new?" + urlencode(params, doseq=True)

    def get_pet_appearance(self, pose: PetPose) -> Optional[PetAppearance]:
        """Returns the pet appearance for the provided pet pose."""
        for appearance in self.appearances:
            if appearance.pose == pose:
                return appearance
        return None

    def check(self, pose: PetPose) -> bool:
        """Returns True if the pet pose provided is valid."""
        return (self._valid_poses & pose) == pose

    def valid_poses(self, override_pose: Optional[PetPose] = None) -> List[PetPose]:
        """Returns a list of valid pet poses."""
        pose = override_pose or self.pose
        return [p for p in CLOSEST_POSES_IN_ORDER[pose] if self.check(pose=p)]

    def _render_items(self):
        """Returns the items in a valid wearable FIFO manner. Mimics DTI's method of getting rid of item conflicts, if you consider the internal list of items to be the closet of this object."""
        temp_items: List[Item] = []
        for item in self.items:
            for temp in self.items:
                if item == temp:
                    continue

                if temp not in temp_items:
                    continue

                intersect_1 = set(item.appearance.occupies).intersection(
                    temp.appearance.occupies + temp.appearance.restricted_zones
                )
                intersect_2 = set(temp.appearance.occupies).intersection(
                    item.appearance.occupies + item.appearance.restricted_zones
                )

                if intersect_1 or intersect_2:
                    temp_items.remove(temp)
            temp_items.append(item)

        return temp_items

    async def _render_layers(
        self, pose: Optional[PetPose] = None
    ) -> List[AppearanceLayer]:
        """Returns the image layers' images in order from bottom to top. You may override the pose."""

        valid_poses = self.valid_poses(pose)

        if len(valid_poses) == 0:
            raise MissingPetAppearance(
                f'Pet Appearance <"{self.species.id}-{self.color.id}"> does not exist with any poses.'
            )

        pose = valid_poses[0]

        pet_appearance = self.get_pet_appearance(pose=pose)

        if pet_appearance is None:
            raise MissingPetAppearance(
                f'Pet Appearance <"{self.species.id}-{self.color.id}"> does not exist.'
            )

        all_layers = []
        all_layers.extend(pet_appearance.layers)
        item_restricted_zones = []
        for item in self._render_items():
            all_layers.extend(item.appearance.layers)

            item_restricted_zones.extend(item.appearance.restricted_zones)

        all_restricted_zones = set(
            item_restricted_zones + pet_appearance.restricted_zones
        )

        visible_layers = filter(
            lambda layer: layer.zone not in all_restricted_zones, all_layers
        )

        return sorted(visible_layers, key=lambda layer: layer.zone.depth)

    async def render(
        self, fp: Union[BinaryIO, PathLike], pose: Optional[PetPose] = None,
    ):
        """Outputs the rendered pet with the desired emotion + gender presentation to the file-like object passed.

        It is suggested to use something like BytesIO as the object, since this function can take a second or so since it downloads every layer.
        """
        pose = pose or self.pose

        from PIL import Image
        from io import BytesIO

        sizes = {
            LayerImageSize.SIZE_150: 150,
            LayerImageSize.SIZE_300: 300,
            LayerImageSize.SIZE_600: 600,
        }

        img_size = sizes[self.size or LayerImageSize.SIZE_600]

        canvas = Image.new("RGBA", (img_size, img_size))

        layers = await self._render_layers(pose)

        # download images simultaneously
        images = await asyncio.gather(
            *[self.state.http.get_binary_data(layer.image_url) for layer in layers]
        )

        for layer, image in zip(layers, images):
            try:
                layer_image = BytesIO(image)
                foreground = Image.open(layer_image)
            except Exception:
                raise BrokenAssetImage(
                    f"Layer image broken: <Data species={self.species!r} color={self.color!r} pose={pose!r} layer={layer!r}>"
                )
            finally:
                if foreground.mode == "1":  # bad
                    continue
                if foreground.mode != "RGBA":
                    foreground = foreground.convert("RGBA")
                canvas = Image.alpha_composite(canvas, foreground)

        canvas.save(fp, format="PNG")
        fp.seek(0)


class Outfit(Object):
    __slots__ = (
        "state",
        "id",
        "name",
        "pet_appearance",
        "worn_items",
        "closeted_items",
    )

    def __init__(self, *, state: State, **data):
        self.state = state
        self.id = data["id"]
        self.name = data["name"]
        self.pet_appearance = PetAppearance(data=data["petAppearance"], state=state)
        self.worn_items = [Item(**item_data) for item_data in data["wornItems"]]
        self.closeted_items = [Item(**item_data) for item_data in data["closetedItems"]]

    @property
    def url(self) -> str:
        """Returns the outfit URL for the ID provided."""
        return f"https://impress.openneo.net/outfits/{self.id}"

    @property
    def image_urls(self):
        """Returns a dict of the different sizes for the rendered image url of an outfit for the ID provided."""
        new_id = str(self.id).zfill(9)
        id_folder = new_id[:3] + "/" + new_id[3:6] + "/" + new_id[6:]
        url = f"https://openneo-uploads.s3.amazonaws.com/outfits/{id_folder}/"

        urls = {
            "large": url + "preview.png",
            "medium": url + "medium_preview.png",
            "small": url + "small_preview.png",
        }

        return urls

    async def render(
        self,
        fp: Union[BinaryIO, PathLike],
        pose: Optional[PetPose] = None,
        size: Optional[LayerImageSize] = None,
    ):
        """Exports a rendered customization image to the file-like object provided."""
        pose = pose or self.pet_appearance.pose
        neopet = await Neopet.fetch_assets_for(
            species=self.pet_appearance.species,
            color=self.pet_appearance.color,
            pose=pose,
            size=size,
            item_ids=[item.id for item in self.worn_items],
            state=self.state,
        )
        await neopet.render(fp)

    def __repr__(self):
        return f"<Outfit id={self.id} appearance={self.pet_appearance!r}>"
