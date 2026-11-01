// SPDX-License-Identifier: GPL-2.0
/* Legacy HP InstrumentedBIOS WMI read and write interface. */
#include <linux/module.h>
#include <linux/acpi.h>
#include <linux/debugfs.h>
#include <linux/seq_file.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>

static const char * const guids[] = {
 "8232DE3C-663D-4327-A8F4-E293ADB9BF05", /* string */
 "8232DE3D-663D-4327-A8F4-E293ADB9BF05", /* integer */
 "8232DE3E-663D-4327-A8F4-E293ADB9BF05", /* enumeration */
 "8232DE3F-663D-4327-A8F4-E293ADB9BF05", /* ordered list */
};
static struct dentry *dir;
static void dump_obj(struct seq_file *s, const union acpi_object *obj, int depth)
{
 unsigned int i;
 if (depth > 8) { seq_puts(s, "depth-limit\n"); return; }
 switch (obj->type) {
 case ACPI_TYPE_INTEGER:
  seq_printf(s, "integer %llu\n", obj->integer.value); break;
 case ACPI_TYPE_STRING:
  seq_printf(s, "string %u ", obj->string.length);
  for (i = 0; i < obj->string.length; i++) seq_printf(s, "%02x", (unsigned char)obj->string.pointer[i]);
  seq_putc(s, '\n'); break;
 case ACPI_TYPE_BUFFER:
  seq_printf(s, "buffer %u ", obj->buffer.length);
  for (i = 0; i < obj->buffer.length; i++) seq_printf(s, "%02x", obj->buffer.pointer[i]);
  seq_putc(s, '\n'); break;
 case ACPI_TYPE_PACKAGE:
  seq_printf(s, "package %u\n", obj->package.count);
  for (i = 0; i < obj->package.count; i++) dump_obj(s, &obj->package.elements[i], depth + 1);
  break;
 default: seq_printf(s, "unsupported %u\n", obj->type);
 }
}
static int probe_show(struct seq_file *s, void *unused)
{
 unsigned int g, i;
 for (g = 0; g < ARRAY_SIZE(guids); g++) {
  int count = wmi_instance_count(guids[g]);
  seq_printf(s, "guid %s count %d\n", guids[g], count);
  if (count > 256) count = 256;
  for (i = 0; count > 0 && i < count; i++) {
   struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
   acpi_status st = wmi_query_block(guids[g], i, &out);
   seq_printf(s, "instance %u status %u\n", i, st);
   if (ACPI_SUCCESS(st) && out.pointer) dump_obj(s, out.pointer, 0);
   kfree(out.pointer);
  }
 }
 return 0;
}
DEFINE_SHOW_ATTRIBUTE(probe);
/* One write per open; response belongs to that file descriptor. */
struct write_ctx { bool done; char result[96]; size_t len; };
static DEFINE_MUTEX(write_lock);
static int write_open(struct inode *inode, struct file *file)
{
 file->private_data = kzalloc(sizeof(struct write_ctx), GFP_KERNEL);
 return file->private_data ? 0 : -ENOMEM;
}
static int write_release(struct inode *inode, struct file *file)
{
 kfree_sensitive(file->private_data);
 return 0;
}
static ssize_t setting_read(struct file *file, char __user *buf, size_t n, loff_t *ppos)
{
 struct write_ctx *ctx = file->private_data;
 if (!ctx->done) return -ENODATA;
 return simple_read_from_buffer(buf, n, ppos, ctx->result, ctx->len);
}
static ssize_t setting_write(struct file *file, const char __user *buf, size_t n, loff_t *ppos)
{
 static const char *guid = "C9B590D8-E7E4-4DC5-BB0F-CB8A3522027E";
 struct write_ctx *ctx = file->private_data;
 struct acpi_buffer input, output = { ACPI_ALLOCATE_BUFFER, NULL };
 union acpi_object *obj;
 unsigned char *data;
 size_t off = 0, i;
 acpi_status status;
 if (ctx->done || *ppos) return -EINVAL;
 if (n < 6 || n > 3072) return -EINVAL;
 data = memdup_user(buf, n);
 if (IS_ERR(data)) return PTR_ERR(data);
 for (i = 0; i < 3; i++) {
  size_t len, j;
  if (off + 2 > n) goto invalid;
  len = data[off] | ((size_t)data[off + 1] << 8);
  off += 2;
  if ((len & 1) || len > 1022 || off + len > n || (i == 0 && !len)) goto invalid;
  for (j = 0; j < len; j += 2)
   if (!data[off + j] && !data[off + j + 1]) goto invalid;
  off += len;
 }
 if (off != n) goto invalid;
 input.length = n;
 input.pointer = data;
 mutex_lock(&write_lock);
 status = wmi_evaluate_method(guid, 0, 1, &input, &output);
 mutex_unlock(&write_lock);
 obj = output.pointer;
 if (ACPI_FAILURE(status))
  ctx->len = scnprintf(ctx->result, sizeof(ctx->result), "acpi-error %u\n", status);
 else if (!obj || obj->type != ACPI_TYPE_INTEGER)
  ctx->len = scnprintf(ctx->result, sizeof(ctx->result), "unexpected-output %u\n", obj ? obj->type : 0);
 else
  ctx->len = scnprintf(ctx->result, sizeof(ctx->result), "return %llu\n", obj->integer.value);
 ctx->done = true;
 kfree(output.pointer);
 kfree_sensitive(data);
 return n;
invalid:
 kfree_sensitive(data);
 return -EINVAL;
}
static const struct file_operations setting_fops = {
 .owner = THIS_MODULE, .open = write_open, .release = write_release,
 .read = setting_read, .write = setting_write,
};
static int __init probe_init(void)
{
 dir = debugfs_create_dir("hpconfig_legacy", NULL);
 if (IS_ERR_OR_NULL(dir)) return -ENODEV;
 debugfs_create_file("raw", 0400, dir, NULL, &probe_fops);
 debugfs_create_file("set", 0600, dir, NULL, &setting_fops);
 return 0;
}
static void __exit probe_exit(void) { debugfs_remove_recursive(dir); }
module_init(probe_init);
module_exit(probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Legacy HP BIOS WMI configuration interface");
