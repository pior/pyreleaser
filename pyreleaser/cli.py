import fileinput
import pathlib
import re
import subprocess
import functools

import click


def handle_errors(func):
    @functools.wraps(func)
    def decorator(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except subprocess.CalledProcessError as err:
            raise click.ClickException(err)
    return decorator


def title(msg):
    print(f'🔸  {msg}')


def capture(args, check=True):
    result = subprocess.run(args, check=check, stdout=subprocess.PIPE)
    return result.stdout.strip().decode()


def get_git_branch():
    return capture(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])


def get_git_tags(remote=False):
    if remote:
        output = capture(['git', 'ls-remote', '--tags', 'origin'])
    else:
        output = capture(['git', 'show-ref', '--tags'], check=False)

    lines = re.findall(r'refs/tags/([^^\n]+)', output)
    return list(set(lines))


def is_git_clean():
    result = subprocess.run(
        ['git', 'diff-index', '--quiet', 'HEAD', '--'],
        check=False,
        stdout=subprocess.PIPE,
    )
    return result.returncode == 0


def read_version_setup_py():
    output = capture(['python', 'setup.py', '--version'])
    return output


def update_version_setup_py(version):
    changed = False
    for line in fileinput.input('setup.py', inplace=True):
        if re.match(r'VERSION\s*=', line):
            print(f"VERSION = '{version}'  # maintained by release tool")
            changed = True
        else:
            print(line, end='')
    return changed


def run_checks(version, tag_name, only_on):
    if only_on:
        current_branch = get_git_branch()
        if current_branch != only_on:
            raise click.ClickException(f'not on the {only_on} branch. ({current_branch})')

    if not is_git_clean():
        raise click.ClickException('uncommited files')

    if tag_name in get_git_tags(remote=False):
        raise click.ClickException(f'tag already exists locally ({tag_name})')

    if tag_name in get_git_tags(remote=True):
        raise click.ClickException(f'tag already exists remotely ({tag_name})')

    if not pathlib.Path('setup.py').exists():
        raise click.ClickException('missing setup.py file')

    if version == read_version_setup_py():
        raise click.ClickException(f'{version} is already the current version')


def run_release(version, tag_name):
    title('Update version in setup.py')
    changed = update_version_setup_py(version)
    if not changed:
        raise click.ClickException('failed to update setup.py')

    title('Commit the release')
    subprocess.run(['git', 'add', 'setup.py'], check=True)
    subprocess.run(['git', 'commit', '-m', f'Release {tag_name}'], check=True)

    title(f'Tag the release: {tag_name}')
    subprocess.run(['git', 'tag', '-a', '-m', f'Release {tag_name}', tag_name], check=True)


def run_push(push):
    if push:
        title('Pushing to git upstream')
        subprocess.run(['git', 'push', '--follow-tags'], check=True)
    else:
        print(f'\n🔔  Don\'t forget to push with: git push --follow-tags')


def update_version(current_version, upgrade_type):
    split_version = current_version.split('.')
    new_split = []
    if upgrade_type == 'major':
        new_split.append(int(split_version[0]) + 1)
        new_split.append(0)
        new_split.append(0)
    elif upgrade_type == 'minor':
        new_split.append(int(split_version[0]))
        new_split.append(int(split_version[1]) + 1)
        new_split.append(0)
    else:
        new_split.append(int(split_version[0]))
        new_split.append(int(split_version[1]))
        if len(split_version) == 2:
            new_split.append(1)
        else:
            new_split.append(int(split_version[2]) + 1)
    return '.'.join(map(str, new_split))


@click.command()
@click.option('--only-on', metavar='BRANCH-NAME')
@click.option('--push', is_flag=True)
@click.argument('version')
@handle_errors
def create(version, push, only_on):

    if re.search(r'^[v]*[0-9]+\.[0-9]+[\.\[0-9\]+]*$', version):
        new_version = version.lstrip('v')
        tag_name = f'v{version}'
    elif version in ['major', 'minor', 'patch']:
        current_version = read_version_setup_py()
        new_version = update_version(current_version, version)
        tag_name = f'v{new_version}'
    else:
        raise click.ClickException(
            f'{version} is not a valid version or semantic version upgrade type.'
        )

    run_checks(new_version, tag_name, only_on)
    run_release(new_version, tag_name)
    run_push(push)


def build_distributions():
    subprocess.run(['rm', '-rf', 'dist'], check=True)

    result = subprocess.run(
        ['python', 'setup.py', 'sdist', 'bdist_wheel'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if result.returncode != 0:
        print(result.stdout.decode())
        raise click.ClickException('failed to build distribution')


@click.command()
@click.option('--dry-run', is_flag=True)
@handle_errors
def upload(dry_run):
    title('Build distributions')
    build_distributions()

    title('Upload to PyPI')
    args = ['twine', 'upload', 'dist/*']
    if not dry_run:
        subprocess.run(args, check=True)
    else:
        print(f'Not running: {args}')


@click.group()
def main():
    pass


main.add_command(create)
main.add_command(upload)
