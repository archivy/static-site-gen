from pathlib import Path
from shutil import rmtree, copytree
from sys import exit

import click
import frontmatter
from flask import render_template
from flask_login import UserMixin

from archivy import app
from archivy.data import get_item, get_items, Directory, get_data_dir
from archivy.forms import DeleteDataForm, NewFolderForm, DeleteFolderForm


display_post = lambda post: "omit" not in post.metadata or not post["omit"]


class LoggedInUser(UserMixin):
    is_authenticated = True


def process_render(route, **kwargs):
    resp = render_template(route, **kwargs, current_user=LoggedInUser(), view_only=1)
    return resp.replace("?path=", "dirs/")


def gen_dir_page(
    directory: Directory, output_path: Path, parent_dir: Path, dataobj_tree
):
    new_dir_path = output_path / parent_dir / directory.name
    new_dir_path.mkdir()

    if directory.child_files or directory.child_dirs:
        with (new_dir_path / "index.html").open("w") as f:
            parent_path = str(parent_dir.relative_to(output_path))
            if parent_path == ".":
                parent_path = ""
            f.write(
                process_render(
                    "home.html",
                    dir=directory,
                    title=f"{parent_path}{directory.name}",
                    current_path=f"{parent_path}/{directory.name}/",
                    new_folder_form=NewFolderForm(),
                    delete_form=DeleteFolderForm(),
                    dataobjs=dataobj_tree,
                )
            )

        for child_dir in directory.child_dirs.values():
            gen_dir_page(child_dir, output_path, new_dir_path, dataobj_tree)


def strip_hidden_data(directory: Directory):
    directory.child_files = list(filter(display_post, directory.child_files))
    for subdir in list(directory.child_dirs.keys()):
        stripped_subdir = strip_hidden_data(directory.child_dirs[subdir])
        if not stripped_subdir:
            directory.child_dirs.pop(subdir)
        else:
            directory.child_dirs[subdir] = stripped_subdir
    if directory.child_files or directory.child_dirs:
        return directory
    return None


@click.group()
def static_site():
    pass


@static_site.command()
@click.option(
    "--overwrite", help="Overwrite _site/ output directory if it exists", is_flag=True
)
def build(overwrite):
    output_path = Path().absolute() / "_site"
    if output_path.exists():
        if overwrite:
            rmtree(output_path)
        else:
            click.echo("Output directory already exists.")
            exit(1)

    output_path.mkdir()

    app.config["SERVER_NAME"] = "localhost:5000"
    copytree(app.static_folder, (output_path / "static"))

    dataobj_dir = output_path / "dataobj"
    dataobj_dir.mkdir()
    with app.test_request_context():
        dataobj_tree = strip_hidden_data(get_items())

        # clean up dataobj tree to only show displayed data
        items = filter(display_post, get_items(structured=False))
        for post in items:
            (dataobj_dir / str(post["id"])).mkdir()
            with (dataobj_dir / str(post["id"]) / "index.html").open("w") as f:
                f.write(
                    process_render(
                        "dataobjs/show.html",
                        dataobj=post,
                        form=DeleteDataForm(),
                        current_path=post["fullpath"],
                        dataobjs=dataobj_tree,
                        title=post["title"],
                    )
                )

        with (output_path / "index.html").open("w") as f:
            home_dir_page = process_render(
                "home.html",
                new_folder_form=NewFolderForm(),
                delete_form=DeleteFolderForm(),
                dir=dataobj_tree,
                title="Home",
            )
            f.write(home_dir_page)

        directories_dir = output_path / "dirs"
        directories_dir.mkdir()
        with (directories_dir / "index.html").open("w") as f:
            f.write(home_dir_page)
        for child_dir in dataobj_tree.child_dirs.values():
            gen_dir_page(child_dir, directories_dir, directories_dir, dataobj_tree)


@static_site.command()
@click.argument("files", type=click.Path(), nargs=-1)
@click.option(
    "--reverse",
    help="Undo ignoring of certain data when building.",
    is_flag=True,
    default=True,
)
def omit(files, reverse):
    with app.app_context():
        for path in files:
            cur_path = Path(path)
            if path.endswith(".md") and cur_path.resolve().is_relative_to(
                get_data_dir()
            ):
                curr_data = frontmatter.load(path)
                curr_data["omit"] = reverse
                with open(cur_path, "w", encoding="utf-8") as f:
                    f.write(frontmatter.dumps(curr_data))
    print("Saved changes to configuration of data rendered.")
