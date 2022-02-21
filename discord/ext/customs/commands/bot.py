from discord.ext.commands.errors import CommandNotFound
from .exceptions import *
import typing, discord
from .command import Command
from .context import Context
from .params import Parameter
import inspect, discord
from . import models
import traceback
from .feature import Feature
from .slash import *
from discord.http import Route
import json
from .models import Skipping

class Bot(discord.Client):
    def __init__(self, command_prefix : str = None, *args, **kwargs):
        super().__init__(enable_debug_events=True, *args, **kwargs)
        self.command_prefix = command_prefix
        self.commands = models.Set()  
        self.features = models.Set()
        self.slash_commands = models.Set()
        self.queue_slash = []
        self.slash_created = False

    async def on_socket_raw_receive(self, msg: dict):
        msg = json.loads(msg)
        if msg["t"] == "INTERACTION_CREATE":
            return await self.interaction_created(msg)

    async def get_slash_context(self, interaction: discord.Interaction, command: SlashCommand):
        return SlashContext(bot=self, interaction=interaction, command=command)

    async def interaction_created(self, msg: dict):
        while self.slash_created is True:
            interaction = discord.Interaction(state=self._connection, data=msg["d"])
            command = self.slash_commands.get((msg["d"]["data"])["name"])
            if not command:
                raise CommandNotFound(f"Slash command \"{(msg['d']['data'])['name']}\"")
            context = await self.get_slash_context(interaction, command)
            return await context.command(context)

    async def create_slash(self, name: str, callback, type: int = 1, description: str = "A slash cmd.", guild_id: int = None):
        application_id = (await self.application_info()).id
        route = Route("POST", f"/applications/{application_id}/commands" if not guild_id else f"/applications/{application_id}/guilds/{guild_id}/commands")
        data = {"type": type, "name": name, "description": description}
        posted = await self.http.request(route, headers={"Content-Type": "application/json"}, json=data)
        slash = SlashCommand(name, callback, description)
        self.slash_commands.set(name, slash)
        self.slash_created = True

    def reload_feature(self, name: str, *args, **kwargs):
        f: Feature = self.features.get(name)
        self.features.remove(name)
        self.integrate_feature(f.__class__(self, *args, **kwargs))

    def remove_feature(self, name: str):
        self.features.remove(name)

    def integrate_feature(self, feature):
        self.features.set(feature.name, feature)
        return feature

    def get_feature(self, name : str):
        data = self.features.get(name)
        if not data:
            return None
        return data
 
    def get_command(self, name : str):
        data = self.commands.get(name)
        if not data:
            return None
        return data

    async def on_message(self, message : discord.Message):
        if message.author.id == self.user.id:
            return
        return await self.process_commands(message)     

    async def process_commands(self, message : discord.Message):
        context = await self.get_context(message, cls=Context)
        return await self.invoke(context) 

    async def invoke(self, ctx: Context):
        try:
            skipper = Skipping(ctx.message.content)
            skip = skipper.skip(self.command_prefix)
            if skip:
                ctx.message.content = skip
                found_command = [cmd for cmd in self.commands._dict if ctx.message.content.startswith(cmd)]
                if not found_command:
                    raise CommandNotFound(f"Command \"{ctx.message.content}\" not found")
                found_command = found_command[0]
                ctx.command = found_command
                content = skip.split(found_command)
                content = "".join(content)
                content = content.lstrip(" ")
                args = content.split(' ')
                command = self.commands.get(found_command)
                command_parameters = [param for param in (inspect.signature(command.callback))._parameters.keys() if param != "ctx"]
                needed_parameters = command_parameters
                parameters = dict(zip(needed_parameters, args))

                return await command(ctx, **parameters)
            else:
                return
        except Exception as e:
            traceback.print_exc()
            return await raise_error(CommandError(f"{e}", status_code=1, traceback="Error"))

    def add_command(self, func : typing.Callable, name : str, description : str, feature = None):
        if not isinstance(func, typing.Callable):
            raise CommandInvokeError(f'Failed to add command {name}: Not Function')
        params = [param for param in (inspect.signature(func))._parameters.keys()]
        param_names = []
        if not params:
            self.commands.set(name, value=Command(name=name, callback=func, description=description, args=None, feature=feature or self))
        else:
            for param in params:
                param_names.append(Parameter(name=param))
            first_param = param_names[0]
            command = Command(name=name, callback=func, description=description, args=param_names)                    
            cmd = self.commands.get(name)
            return self.commands.set(name=name, value=command)  
                                            
    def command(self, name : str = None, description : str = None):
        if self.command_prefix is None:
            raise RuntimeError("No command_prefix set.")                                  
        def command_wrapper(func : typing.Callable) -> typing.Callable:
            self.add_command(func, name = name or func.__name__, description = description)
        return command_wrapper
        
    async def get_context(self, message : discord.Message, cls : Context = Context):
        try:
            context = cls(message=message, author=message.author, channel=message.channel, guild=message.guild, bot=self) 
            return context
        except Exception:
            return await raise_error(MissingParameter("A parameter is missing", status_code=1, traceback="Internal Error: Missing Parameter"))

class AutoShardedBot(Bot, discord.AutoShardedClient):
    pass  